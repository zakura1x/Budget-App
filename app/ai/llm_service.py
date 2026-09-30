"""
The only code in ZBDGT that talks to watsonx.ai (misc/AI ARCHITECTURE §3, §12).

Copied on 2026-09-30 from STWRD (services/llm_service.py), which copied it from
DMS, which ported it from QUOT. Kept as they have it: the model cache per
model and parameters, parameter-name normalisation, invoke_with_recovery's
retry after an auth error with a cache clear and a credential reload, and the
JSON repair helper. Added by DMS, and kept:

- The kill switch - here AI_ENABLED (STWRD: WATSONX_ENABLED). While it is
  false, get_llm_service() refuses and nothing loads credentials or starts the
  loader's thread.
- Concurrency limits. A model call blocks a request thread for its whole
  duration, so calls are capped per user and per process
  (ConcurrencyLimitReached is raised rather than queueing). ZBDGT runs ONE
  uvicorn worker (invariant 7), so here the per-user limit is exact, not best
  effort as it is across STWRD's FastCGI processes.
- health(), for GET /assistant/health and scripts/ai_health.py.

Changed for ZBDGT: settings from app.core.config; STWRD's check for its
conversation tables is gone (A1 has none); a reply is logged as its length
and token counts - plain integers, which pass the redaction filter - and a
prompt or reply text is never logged (AI-52).
"""

import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class AssistantDisabled(RuntimeError):
    """AI_ENABLED is false"""


class ConcurrencyLimitReached(RuntimeError):
    """The user or the process already has the maximum calls in flight"""


# ==============================================================
# CONCURRENCY
# ==============================================================

class ConcurrencyGuard:
    """Caps in-flight model calls per user and per process."""

    def __init__(self, per_user: int, per_process: int):
        self.per_user = max(1, per_user)
        self._process = threading.BoundedSemaphore(max(1, per_process))
        self._lock = threading.Lock()
        self._in_flight: Dict[Any, int] = {}

    @contextmanager
    def slot(self, user_id):
        with self._lock:
            if self._in_flight.get(user_id, 0) >= self.per_user:
                raise ConcurrencyLimitReached("You already have a question in progress.")
            self._in_flight[user_id] = self._in_flight.get(user_id, 0) + 1

        acquired = self._process.acquire(blocking=False)

        try:
            if not acquired:
                raise ConcurrencyLimitReached("The assistant is busy. Please try again in a moment.")
            yield

        finally:
            if acquired:
                self._process.release()

            with self._lock:
                remaining = self._in_flight.get(user_id, 1) - 1
                if remaining:
                    self._in_flight[user_id] = remaining
                else:
                    self._in_flight.pop(user_id, None)


# ==============================================================
# SERVICE
# ==============================================================

class LLMService:

    # watsonx text generation names these differently from the OpenAI-style
    # spellings. An unrecognised key is silently dropped and max_new_tokens
    # falls back to 20, which truncates every reply mid-sentence.
    _PARAM_ALIASES = {
        "max_tokens": "max_new_tokens",
        "max_output_tokens": "max_new_tokens",
        "min_tokens": "min_new_tokens",
    }

    _AUTH_ERROR_MARKERS = (
        "auth", "unauthorized", "authentication", "apikey", "token", "401", "403", "credential",
    )

    def __init__(self, credential_loader=None):
        if credential_loader is None:
            from app.ai.credential_loader import AutoReloadCredentialLoader
            credential_loader = AutoReloadCredentialLoader()

        self.credential_loader = credential_loader
        self._llm_cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def normalise_params(cls, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not params:
            return {}

        normalised = {cls._PARAM_ALIASES.get(key, key): value for key, value in params.items()}

        # temperature only takes effect under sampling; under the default
        # greedy decoding it is accepted and ignored.
        if "decoding_method" not in normalised:
            normalised["decoding_method"] = "sample" if normalised.get("temperature") else "greedy"

        return normalised

    @staticmethod
    def _cache_key(model_name: str, params: Dict[str, Any]) -> str:
        return f"{model_name}_{json.dumps(params, sort_keys=True)}"

    def _build_model(self, model_name: str, params: Dict[str, Any], creds: Dict[str, Any]):
        """The watsonx model object. Separate so tests can replace it without the SDK."""
        from app.ai.watsonx_client import WatsonxChatModel

        return WatsonxChatModel(
            model_id=model_name,
            credentials={
                "url": creds.get("ibm_cloud_url") or settings.WATSONX_URL,
                "apikey": creds.get("api_key"),
            },
            project_id=creds.get("project_id"),
            params=params,
            timeout_seconds=settings.WATSONX_TIMEOUT,
        )

    def get_llm(self, model_name: str, params: Dict[str, Any]):
        """A cached WatsonxChatModel for this model and these parameters"""
        params = self.normalise_params(params)
        key = self._cache_key(model_name, params)

        with self._cache_lock:
            if key in self._llm_cache:
                return self._llm_cache[key]

        creds = self.credential_loader.get_watson_credentials_with_retry()

        if not creds:
            raise RuntimeError("No watsonx credentials available from IAM")

        model = self._build_model(model_name, params, creds)

        with self._cache_lock:
            self._llm_cache.setdefault(key, model)
            return self._llm_cache[key]

    def invoke_with_usage(self, model_name: str, params: Dict[str, Any], prompt: str):
        self.credential_loader.check_and_auto_reload()

        started = time.perf_counter()
        text, usage = self.get_llm(model_name, params).invoke_with_usage(prompt)

        logger.info(
            "LLM response model=%s length=%d prompt_tokens=%d completion_tokens=%d elapsed_ms=%d",
            model_name, len(text), int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0), int((time.perf_counter() - started) * 1000),
        )

        return text, usage

    def invoke(self, model_name: str, params: Dict[str, Any], prompt: str) -> str:
        return self.invoke_with_usage(model_name, params, prompt)[0]

    def invoke_with_recovery(
        self,
        model_name: str,
        params: Dict[str, Any],
        prompt: str,
        max_retries: Optional[int] = None,
    ):
        """
        (reply, usage), retrying only after an authentication error.

        On an auth error the cached model is dropped and a credential reload is
        triggered before trying again. Anything else - a timeout above all -
        is raised at once: retrying a timeout doubles the time a request thread
        is blocked.
        """
        attempts = max_retries if max_retries is not None else settings.WATSONX_MAX_RETRIES
        attempts = max(1, attempts)

        for attempt in range(attempts):
            try:
                return self.invoke_with_usage(model_name, params, prompt)

            except Exception as error:
                message = str(error).lower()
                is_auth_error = any(marker in message for marker in self._AUTH_ERROR_MARKERS)

                if not is_auth_error or attempt == attempts - 1:
                    raise

                logger.warning(
                    "LLM auth error (attempt %s/%s) for %s; reloading credentials",
                    attempt + 1, attempts, model_name,
                )

                key = self._cache_key(model_name, self.normalise_params(params))
                with self._cache_lock:
                    stale = self._llm_cache.pop(key, None)
                if stale:
                    stale.close()

                self.credential_loader.trigger_auto_reload()
                time.sleep(self._RELOAD_WAIT_SECONDS)

    # How long a retry after an auth error waits for the background reload
    _RELOAD_WAIT_SECONDS = 3

    def invoke_json(self, model_name: str, params: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """The reply parsed as JSON, repairing the usual model wrappings"""
        response, _ = self.invoke_with_recovery(model_name, params, prompt)

        match = re.search(r"\{[\s\S]*\}", response)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            cleaned = self._clean_response_for_json(response)
            if cleaned:
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    pass

        # Never the reply itself: it may carry the user's figures (AI-52)
        raise ValueError(f"Failed to parse JSON from a reply of {len(response)} characters")

    @staticmethod
    def _clean_response_for_json(response: str) -> Optional[str]:
        response = re.sub(r"```json\s*", "", response)
        response = re.sub(r"```\s*", "", response)
        match = re.search(r"\{[\s\S]*\}", response)
        return match.group(0) if match else None

    def refresh_all_llms(self):
        with self._cache_lock:
            models = list(self._llm_cache.values())
            self._llm_cache.clear()
        for model in models:
            model.close()


# ==============================================================
# PROCESS-WIDE INSTANCES
# ==============================================================
# The credential loader starts a background thread that is never stopped, so
# there is one LLMService per process, built on first use and never while the
# assistant is switched off.

_llm_service: Optional[LLMService] = None
_llm_service_lock = threading.Lock()

concurrency_guard = ConcurrencyGuard(
    per_user=settings.AI_MAX_CONCURRENT_PER_USER,
    per_process=settings.AI_MAX_CONCURRENT_CALLS,
)


def is_enabled() -> bool:
    return settings.AI_ENABLED


def is_allowed(user_id: int) -> bool:
    """AI_ENABLED, and the user is on the pilot list when there is one (AI-54)."""
    if not is_enabled():
        return False
    pilot = settings.ai_allowed_user_ids
    return not pilot or user_id in pilot


def get_llm_service() -> LLMService:
    """The shared LLMService. Raises AssistantDisabled when switched off."""
    global _llm_service

    if not is_enabled():
        raise AssistantDisabled("The AI assistant is switched off (AI_ENABLED=false).")

    if _llm_service is None:
        with _llm_service_lock:
            if _llm_service is None:
                _llm_service = LLMService()

    return _llm_service


def set_llm_service(service: Optional[LLMService]) -> None:
    """Tests only: install a service built on a fake loader, or reset to None."""
    global _llm_service
    with _llm_service_lock:
        _llm_service = service


# ==============================================================
# HEALTH
# ==============================================================

def health(check_model: bool = True) -> Dict[str, Any]:
    """
    What GET /assistant/health reports. Each check says what it found; nothing
    is assumed healthy because an earlier check passed.

    While AI_ENABLED is false this returns at once, without loading
    credentials or starting anything.
    """
    report: Dict[str, Any] = {
        "enabled": is_enabled(),
        "model": settings.WATSONX_CHAT_MODEL,
        "company": settings.COMPANY_NAME,
        "timeout_seconds": settings.WATSONX_TIMEOUT,
        "checks": {},
    }

    if not is_enabled():
        report["status"] = "disabled"
        return report

    service = get_llm_service()

    started = time.perf_counter()
    try:
        creds = service.credential_loader.get_watson_credentials_with_retry()
        accepted = bool(creds) and creds.get("_test_status") == "success"
        report["checks"]["credentials"] = {
            "ok": accepted,
            "detail": ("loaded and accepted by IBM Cloud"
                       + (" - but IAM's record still marks this key expired; update its expiry fields"
                          if creds.get("_iam_marked_expired") else "")) if accepted
            else (service.credential_loader.last_error
                  or ("loaded but rejected by IBM Cloud" if creds else "could not be loaded from IAM")),
            "ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as error:
        report["checks"]["credentials"] = {"ok": False, "detail": f"error: {error.__class__.__name__}"}

    if check_model and report["checks"]["credentials"].get("ok"):
        started = time.perf_counter()
        try:
            text, _usage = service.invoke_with_recovery(
                settings.WATSONX_CHAT_MODEL,
                {"max_new_tokens": 5, "decoding_method": "greedy"},
                "Reply with the single word OK.",
                max_retries=1,
            )
            report["checks"]["model"] = {
                "ok": bool(text.strip()),
                "detail": "replied" if text.strip() else "empty reply",
                "ms": int((time.perf_counter() - started) * 1000),
            }
        except Exception as error:
            report["checks"]["model"] = {
                "ok": False,
                "detail": describe_model_error(error),
                "ms": int((time.perf_counter() - started) * 1000),
            }

    checks = report["checks"].values()
    report["status"] = "ok" if checks and all(c.get("ok") for c in checks) else "failing"

    return report


def describe_model_error(error: Exception) -> str:
    message = str(error).lower()

    if "timed out" in message or "timeout" in message:
        return f"timed out after {settings.WATSONX_TIMEOUT}s"
    if "model_not_supported" in message or "not supported" in message or "does not exist" in message \
            or "model_id" in message or "404" in message:
        return f"model '{settings.WATSONX_CHAT_MODEL}' was not accepted"
    if any(marker in message for marker in LLMService._AUTH_ERROR_MARKERS):
        return "authentication failed"

    return f"error: {error.__class__.__name__}"
