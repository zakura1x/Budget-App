"""
The AI companion's plumbing (misc/AI, Phase A1): settings, the kill switch,
the IAM credential loader, the model service, health, usage counts, and the
two A1 routes.

The watsonx SDK and `requests` are never imported here: the loader imports
`requests` lazily and gets a fake one, and LLMService._build_model is replaced
by a fake model. So these run with neither package installed - which is also
the proof that the app does.
"""

import base64
import logging
import secrets
import sys
import types
from datetime import date, timedelta

import pytest

from app.ai import llm_service
from app.ai.llm_service import AssistantDisabled, ConcurrencyGuard, ConcurrencyLimitReached, LLMService
from app.core.config import ConfigurationError, load_settings, settings
from app.core.logging_config import redact
from app.db.models import AssistantUsage
from app.services.assistant_service import usage

GOOD_KEY = base64.b64encode(secrets.token_bytes(32)).decode()
GOOD_PEPPER = base64.b64encode(secrets.token_bytes(32)).decode()


def build(**overrides):
    values = {"BUDGET_MASTER_KEY": GOOD_KEY, "BUDGET_BLIND_INDEX_PEPPER": GOOD_PEPPER}
    values.update(overrides)
    return load_settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def _no_shared_service():
    llm_service.set_llm_service(None)
    yield
    llm_service.set_llm_service(None)


# ------------------------------------------------------------------ settings


def test_off_by_default_and_iam_settings_not_checked_while_off():
    s = build()
    assert s.AI_ENABLED is False
    assert (s.COMPANY_NAME, s.IAM_MANAGEMENT_URL) == ("", "")
    assert s.WATSONX_CHAT_MODEL == "ibm/granite-4-h-small"
    assert s.ai_allowed_user_ids == frozenset()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"AI_ENABLED": True, "IAM_MANAGEMENT_URL": "https://iam.example"}, "COMPANY_NAME must be set"),
        ({"AI_ENABLED": True, "COMPANY_NAME": "ACME"}, "IAM_MANAGEMENT_URL must be an http"),
        ({"AI_ENABLED": True, "COMPANY_NAME": "ACME", "IAM_MANAGEMENT_URL": "iam.example"}, "IAM_MANAGEMENT_URL"),
        ({"AI_ENABLED": True, "COMPANY_NAME": "ACME", "IAM_MANAGEMENT_URL": "https://iam.example",
          "WATSONX_URL": "http://us-south.ml.cloud.ibm.com"}, "WATSONX_URL must be an https"),
        ({"AI_REPLY_LANGUAGE": "tl"}, "en or match"),
        ({"AI_ALLOWED_USER_IDS": "1,two"}, "entry 2 must be a user id"),
    ],
)
def test_bad_ai_settings_refuse_to_start(overrides, message):
    with pytest.raises(ConfigurationError, match=message):
        build(**overrides)


def test_good_ai_settings_load():
    s = build(AI_ENABLED=True, COMPANY_NAME="ACME", IAM_MANAGEMENT_URL="http://iam.internal:8080",
              AI_ALLOWED_USER_IDS=" 1, 7 ,", AI_REPLY_LANGUAGE="match")
    assert s.ai_allowed_user_ids == frozenset({1, 7})


# ------------------------------------------------------------ the kill switch


def test_switched_off_nothing_loads(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    for name in ("ibm_watsonx_ai", "app.ai.watsonx_client", "app.ai.credential_loader"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    with pytest.raises(AssistantDisabled):
        llm_service.get_llm_service()
    report = llm_service.health()
    assert report["status"] == "disabled" and report["checks"] == {}
    assert llm_service._llm_service is None
    assert "ibm_watsonx_ai" not in sys.modules
    assert "app.ai.watsonx_client" not in sys.modules
    assert "app.ai.credential_loader" not in sys.modules


def test_pilot_list(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    fake = types.SimpleNamespace(AI_ENABLED=True, ai_allowed_user_ids=frozenset({2}))
    monkeypatch.setattr(llm_service, "settings", fake)
    assert llm_service.is_allowed(2) and not llm_service.is_allowed(3)
    fake.ai_allowed_user_ids = frozenset()
    assert llm_service.is_allowed(3)
    fake.AI_ENABLED = False
    assert not llm_service.is_allowed(2)


# -------------------------------------------------------------- concurrency


def test_one_question_in_flight_per_user_and_a_process_cap():
    guard = ConcurrencyGuard(per_user=1, per_process=2)
    with guard.slot(1):
        with pytest.raises(ConcurrencyLimitReached, match="in progress"):
            with guard.slot(1):
                pass
        with guard.slot(2):
            with pytest.raises(ConcurrencyLimitReached, match="busy"):
                with guard.slot(3):
                    pass
    with guard.slot(1), guard.slot(3):  # everything released
        pass


# ------------------------------------------------------------- LLMService


class FakeLoader:
    def __init__(self, creds=None):
        self.creds = creds if creds is not None else {"api_key": "k", "project_id": "p", "_test_status": "success"}
        self.reloads = 0
        self.last_error = None

    def get_watson_credentials_with_retry(self, company_name=None):
        return self.creds

    def check_and_auto_reload(self, company=None):
        return False

    def trigger_auto_reload(self, company=None):
        self.reloads += 1


class FakeModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.closed = False
        self.prompts = []

    def invoke_with_usage(self, prompt, stop=None):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, {"prompt_tokens": 50, "completion_tokens": 7}

    def close(self):
        self.closed = True


def service_with(models, loader=None):
    service = LLMService(credential_loader=loader or FakeLoader())
    queue = list(models)
    service._build_model = lambda name, params, creds: queue.pop(0)
    service._RELOAD_WAIT_SECONDS = 0
    return service


def test_a_model_is_built_once_per_model_and_params():
    model = FakeModel(["one", "two"])
    service = service_with([model])
    assert service.invoke("m", {"max_tokens": 10}, "q") == "one"
    assert service.invoke("m", {"max_new_tokens": 10}, "q") == "two"  # same after normalising


def test_an_auth_error_reloads_and_retries_once():
    loader = FakeLoader()
    stale, fresh = FakeModel([RuntimeError("401 Unauthorized")]), FakeModel(["ok"])
    service = service_with([stale, fresh], loader)
    text, usage_ = service.invoke_with_recovery("m", {}, "q", max_retries=2)
    assert text == "ok" and usage_["completion_tokens"] == 7
    assert loader.reloads == 1 and stale.closed


def test_a_timeout_is_never_retried():
    loader = FakeLoader()
    service = service_with([FakeModel([TimeoutError("Read timed out"), "never"])], loader)
    with pytest.raises(TimeoutError):
        service.invoke_with_recovery("m", {}, "q", max_retries=3)
    assert loader.reloads == 0


def test_no_credentials_is_an_error_not_a_call():
    service = service_with([], FakeLoader(creds={}))
    with pytest.raises(RuntimeError, match="No watsonx credentials"):
        service.invoke("m", {}, "q")


def test_json_repair_and_a_failure_that_does_not_echo_the_reply():
    service = service_with([FakeModel(['```json\n{"intent": "budget_status"}\n```', "no json, PHP 1,234.00"])])
    assert service.invoke_json("m", {}, "q") == {"intent": "budget_status"}
    with pytest.raises(ValueError) as caught:
        service.invoke_json("m", {}, "q")
    assert "1,234" not in str(caught.value)


@pytest.mark.security
def test_prompts_and_replies_are_never_logged(caplog):
    service = service_with([FakeModel(["You have 4210 left for groceries at SM"])])
    with caplog.at_level(logging.DEBUG):
        service.invoke_with_recovery("m", {}, "Can I buy the Lazada headphones for 3999?")
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "LLM response" in logged and "completion_tokens=7" in logged
    assert "Lazada" not in logged and "groceries" not in logged


@pytest.mark.security
def test_the_redaction_filter_hides_a_credentials_dict():
    line = redact("creds={'api_key': 'Zx9-abcDEF_123', 'apikey': 'Qq7-secret', 'project_id': 'p1'}")
    assert "Zx9-abcDEF_123" not in line and "Qq7-secret" not in line


# ------------------------------------------------------- credential loader


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


@pytest.fixture
def fake_requests(monkeypatch):
    """A stand-in `requests`: IAM answers from `iam`, IBM's token endpoint from `ibm`."""
    calls = {"iam": 0, "ibm": 0}
    state = {"iam": FakeResponse(404), "ibm": FakeResponse(400)}

    def get(url, timeout):
        calls["iam"] += 1
        assert url == "https://iam.example/api/watson-credentials/company/ACME"
        return state["iam"]

    def post(url, **kw):
        assert url.startswith("https://iam.cloud.ibm.com/"), "nothing is posted back to IAM"
        calls["ibm"] += 1
        return state["ibm"]

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get, post=post))
    monkeypatch.setattr(settings, "IAM_MANAGEMENT_URL", "https://iam.example/")
    monkeypatch.setattr(settings, "COMPANY_NAME", "ACME")
    return state, calls


@pytest.fixture
def loader():
    from app.ai.credential_loader import AutoReloadCredentialLoader

    created = AutoReloadCredentialLoader(max_retries=2, retry_delay=0)
    yield created
    created.shutdown()


def iam_ok(**data):
    return FakeResponse(200, {"success": True, "data": {"api_key": "k1", "project_id": "p1", **data}})


def test_credentials_are_tested_once_and_then_cached(fake_requests, loader):
    state, calls = fake_requests
    state["iam"], state["ibm"] = iam_ok(), FakeResponse(200)
    creds = loader.get_watson_credentials_with_retry()
    assert creds["_test_status"] == "success" and loader.last_error is None
    loader.get_watson_credentials_with_retry()
    assert calls == {"iam": 1, "ibm": 1}


def test_a_key_iam_marks_expired_is_used_if_ibm_accepts_it(fake_requests, loader):
    state, _ = fake_requests
    state["iam"], state["ibm"] = iam_ok(expired=True, expiration_date="2026-09-01"), FakeResponse(200)
    creds = loader.get_watson_credentials_with_retry()
    assert creds["_iam_marked_expired"] is True


def test_an_expired_key_ibm_rejects_is_remembered_not_retried(fake_requests, loader):
    state, calls = fake_requests
    state["iam"], state["ibm"] = iam_ok(status="Expired", expiration_date="2026-09-01"), FakeResponse(400)
    assert loader.get_watson_credentials_with_retry() is None
    assert "expired on 2026-09-01" in loader.last_error
    assert loader.get_watson_credentials_with_retry() is None
    assert calls == {"iam": 1, "ibm": 1}


def test_iam_down_is_reported(fake_requests, loader):
    state, calls = fake_requests
    state["iam"] = FakeResponse(500)
    assert loader.get_watson_credentials_with_retry() is None
    assert calls["iam"] == 2  # max_retries
    assert "Could not load credentials for ACME" in loader.last_error


# ------------------------------------------------------------------ health


def test_health_when_everything_answers(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    llm_service.set_llm_service(service_with([FakeModel(["OK"])]))
    report = llm_service.health()
    assert report["status"] == "ok"
    assert report["checks"]["credentials"]["detail"] == "loaded and accepted by IBM Cloud"
    assert report["checks"]["model"]["detail"] == "replied"


def test_health_names_what_failed(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    llm_service.set_llm_service(service_with([FakeModel([TimeoutError("Read timed out")])]))
    report = llm_service.health()
    assert report["status"] == "failing"
    assert report["checks"]["model"]["detail"] == f"timed out after {settings.WATSONX_TIMEOUT}s"

    loader = FakeLoader(creds={})
    loader.last_error = "IBM Cloud rejected the API key from IAM"
    llm_service.set_llm_service(service_with([], loader))
    report = llm_service.health()
    assert report["checks"]["credentials"] == {"ok": False, "detail": "IBM Cloud rejected the API key from IAM",
                                               "ms": report["checks"]["credentials"]["ms"]}
    assert "model" not in report["checks"]


# ------------------------------------------------------------------- usage


def test_usage_counts_per_user_per_day(session, monkeypatch):
    monkeypatch.setattr(settings, "AI_MAX_QUESTIONS_PER_DAY", 3)
    today = date(2026, 10, 1)
    usage.record(session, 1, day=today, questions=1, model_calls=2, prompt_tokens=400, completion_tokens=60)
    usage.record(session, 1, day=today, questions=1, model_calls=1, fallbacks=1)
    usage.record(session, 2, day=today, questions=1)
    usage.record(session, 1, day=today - timedelta(days=1), questions=5)
    session.commit()
    assert usage.questions_today(session, 1, day=today) == 2
    assert usage.questions_left(session, 1, day=today) == 1
    assert usage.questions_left(session, 3, day=today) == 3
    totals = usage.totals(session, day=today)
    assert (totals.users, totals.questions, totals.model_calls, totals.prompt_tokens, totals.fallbacks) == (2, 3, 3, 400, 1)
    monkeypatch.setattr(settings, "AI_MAX_QUESTIONS_PER_DAY", 0)
    assert usage.questions_left(session, 1, day=today) is None


def test_deleting_an_account_removes_its_usage(session):
    from sqlalchemy import func, select

    from app.db.repositories.rotation_repository import RotationRepository

    usage.record(session, 1, questions=1)
    usage.record(session, 2, questions=1)
    counts = RotationRepository(session).purge_user(1)
    assert counts["assistant_usage"] == 1
    assert session.execute(select(func.count(AssistantUsage.id))).scalar_one() == 1


# --------------------------------------------------------------- the routes


def test_status_route(api, monkeypatch):
    api.register()
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    off = api.get("/assistant/status").json()
    assert (off["enabled"], off["opted_in"], off["questions_left_today"], off["suggestions"]) == (False, False, 0, [])
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    on = api.get("/assistant/status").json()
    assert (on["enabled"], on["questions_left_today"]) == (True, settings.AI_MAX_QUESTIONS_PER_DAY)
    assert on["suggestions"] and on["reply_language"] == settings.AI_REPLY_LANGUAGE
    assert llm_service._llm_service is None  # status never loads credentials
    api.post("/auth/lock")
    locked = api.get("/assistant/status")
    assert locked.status_code == 401 and locked.json()["code"] == "SESSION_LOCKED"


def test_health_route_is_admin_only(api, monkeypatch):
    api.register(email="admin@example.com")
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    body = api.get("/assistant/health").json()
    assert body["status"] == "disabled" and body["usage_today"]["questions"] == 0
    api.client.cookies.clear()
    api.register(email="bob@example.com")
    assert api.get("/assistant/health").status_code == 403
