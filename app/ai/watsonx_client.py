"""
One watsonx.ai model, called over the chat endpoint (misc/AI ARCHITECTURE §3).

Copied unchanged on 2026-09-30 from STWRD (services/watsonx_client.py), which
copied it from DMS, which replaced QUOT's app/core/langchain_interface.py. The
behaviour kept from QUOT:

- Chat (/ml/v1/text/chat) first, because it applies the model's own chat
  template; plain text generation as a fallback when chat fails.
- Generation-style parameter names are translated for chat. A wrong name is
  not an error to watsonx - it is silently dropped, and the token limit falls
  back to a default that truncates the reply.

What DMS changed, and STWRD and this app keep:

- No LangChain. QUOT subclasses langchain_core's LLM and uses none of it, so
  this calls the SDK directly and does not take the dependency.
- A real timeout. QUOT defines WATSONX_TIMEOUT and never passes it on, so its
  calls use the SDK default read timeout of 30 minutes. A request thread is
  blocked for the whole call, so the timeout is applied to the HTTP client.
- One APIClient and ModelInference per instance, built once. QUOT builds a new
  model object - and so fetches a new token - on every call.

Imported only by LLMService.get_llm(), so only when a question is asked with
AI_ENABLED true. The SDK is never imported by the tests.
"""

import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from ibm_watsonx_ai import APIClient, Credentials
from ibm_watsonx_ai.foundation_models import ModelInference
from ibm_watsonx_ai.utils.utils import HttpClientConfig

logger = logging.getLogger(__name__)


def enforce_stop_tokens(text: str, stop: List[str]) -> str:
    """Cut the text at the first occurrence of any stop token"""
    return re.split("|".join(re.escape(s) for s in stop), text, maxsplit=1)[0]


class WatsonxChatModel:

    # Chat wants OpenAI-style names; generation wants its own.
    _CHAT_PARAM_MAP = {
        "max_new_tokens": "max_tokens",
        "min_new_tokens": None,      # no chat equivalent
        "decoding_method": None,     # chat infers it from temperature
        "random_seed": "seed",
        "repetition_penalty": "frequency_penalty",
    }

    def __init__(
        self,
        model_id: str,
        credentials: Dict[str, str],
        project_id: Optional[str],
        params: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 30,
        max_retries: int = 0,
    ):
        self.model_id = model_id
        self.params = dict(params or {})
        self.timeout_seconds = timeout_seconds

        http_config = HttpClientConfig(
            timeout=httpx.Timeout(timeout_seconds, connect=10),
        )

        self._client = APIClient(
            credentials=Credentials(
                url=credentials["url"],
                api_key=credentials["apikey"],
            ),
            project_id=project_id,
            httpx_client=http_config,
        )

        # max_retries is the SDK's own retry on 429/503. Each retry is another
        # full wait on a blocked request thread, so it defaults to none here;
        # LLMService decides what to retry.
        self._model = ModelInference(
            model_id=model_id,
            api_client=self._client,
            project_id=project_id,
            max_retries=max_retries,
        )

    def _chat_params(self) -> Dict[str, Any]:
        chat_params: Dict[str, Any] = {}

        for key, value in self.params.items():
            if key in self._CHAT_PARAM_MAP:
                mapped = self._CHAT_PARAM_MAP[key]
                if mapped:
                    chat_params[mapped] = value
            else:
                chat_params[key] = value

        # Greedy decoding has no chat flag; temperature 0 is how it is asked for
        if self.params.get("decoding_method") == "greedy":
            chat_params.setdefault("temperature", 0)

        return chat_params

    def invoke(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """The model's reply to a single user message"""
        return self.invoke_with_usage(prompt, stop)[0]

    def invoke_with_usage(self, prompt: str, stop: Optional[List[str]] = None):
        """
        (reply, usage) for a single user message.

        Usage is returned rather than stored on the instance: one instance is
        shared by every request thread in the process.
        """

        try:
            response = self._model.chat(
                messages=[{"role": "user", "content": prompt}],
                params=self._chat_params(),
            )
            text = response["choices"][0]["message"]["content"] or ""
            usage = dict(response.get("usage") or {})

        except Exception as chat_error:
            # A timeout will not get better on the generation endpoint, and
            # retrying it doubles the time a request thread is blocked.
            if isinstance(chat_error, httpx.TimeoutException) or "timed out" in str(chat_error).lower():
                raise

            logger.warning(
                "Chat endpoint failed for %s, falling back to text generation",
                self.model_id,
                exc_info=True,
            )

            response = self._model.generate(prompt=prompt, params=self.params)
            result = response["results"][0]
            text = result["generated_text"]
            usage = {
                "prompt_tokens": result.get("input_token_count", 0),
                "completion_tokens": result.get("generated_token_count", 0),
            }

        if stop:
            text = enforce_stop_tokens(text, stop)

        return text, usage

    def close(self):
        try:
            self._client.httpx_client.close()
        except Exception:
            pass
