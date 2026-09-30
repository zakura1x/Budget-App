"""
The AI companion's model layer (misc/AI, Phase A1).

IBM watsonx.ai, with the API key fetched at runtime from the company IAM
service - the same three modules STWRD runs (D:\\Shared Files\\STWRD_UPDATED
\\services), which came from DMS, which came from QUOT on this same host.

Nothing is imported here on purpose. `llm_service` imports the watsonx SDK
only inside `get_llm()`, and `get_llm_service()` refuses while AI_ENABLED is
false, so the app runs - and every test runs - without the SDK installed.
"""
