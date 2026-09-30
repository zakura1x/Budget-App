"""
watsonx.ai credentials from the company IAM service (misc/AI ARCHITECTURE §3).

Copied on 2026-09-30 from STWRD (services/credential_loader.py), which copied
it unchanged from DMS, which ported it from QUOT. The only changes here: settings
come from app.core.config instead of STWRD's Config class, and `requests` is
imported inside the methods that call it, so the app starts without it. The
behaviour STWRD and DMS keep, and this app keeps:

- The credential cache honours CREDENTIAL_CACHE_TTL. QUOT reads the variable
  and then hardcodes 300 seconds.
- A key IAM reports as expired is tested against IBM once, and not retried.
  If IBM accepts it, it is used - IAM's expiry fields can be stale, as they
  were on 2026-09-17 after the DELCA key was replaced. If IBM rejects it, the
  failure is reported with IAM's expiry date and remembered for the cache TTL,
  instead of being retried three times five seconds apart (seventeen seconds
  of a blocked request).
- Test results are not posted back to IAM unless IAM_REPORT_TEST_STATUS is
  true. QUOT posts them; the record is shared, and this app should not be a
  second writer to it by default.
- check_and_auto_reload does not make a live test call to IBM on every model
  invocation. QUOT's version does, which puts an extra HTTPS round trip in
  front of every answer. Credentials are still tested whenever they are
  fetched, and an auth failure during a call still triggers a reload through
  LLMService.invoke_with_recovery.

The API key lives in this object's memory and nowhere else: never .env, the
database or a log line (the redaction filter also names api_key / apikey).

Only ever constructed through app.ai.llm_service.get_llm_service(), and so
only when AI_ENABLED is true and a model call is actually made. Creating one
starts a background thread.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from queue import Queue
from typing import Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class AutoReloadCredentialLoader:
    """Credential loader with automatic failure detection and recovery"""

    IBM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"

    def __init__(self, max_retries: Optional[int] = None, retry_delay: Optional[int] = None):
        self.base_url = settings.IAM_MANAGEMENT_URL.rstrip("/")
        self.company_name = settings.COMPANY_NAME
        self.cache_ttl = settings.CREDENTIAL_CACHE_TTL
        self.report_test_status = settings.IAM_REPORT_TEST_STATUS

        # Why the last fetch failed, for health checks. None after a success.
        self.last_error: Optional[str] = None

        self.max_retries = max_retries if max_retries is not None else settings.IAM_MAX_RETRIES
        self.retry_delay = retry_delay if retry_delay is not None else settings.IAM_RETRY_DELAY

        self._credentials_cache: Dict[str, Dict] = {}
        # company -> time until which an expired key is not re-fetched
        self._expired_until: Dict[str, datetime] = {}
        self._failure_count: Dict[str, int] = {}
        self._lock = threading.Lock()

        self._reload_queue: Queue = Queue()
        self._reload_thread = None
        self._running = True

        self.stats = {
            "start_time": datetime.now(),
            "total_requests": 0,
            "cache_hits": 0,
            "reloads_attempted": 0,
            "reloads_successful": 0,
            "reloads_failed": 0,
            "last_failure": None,
            "last_success": None,
        }

        self._start_reload_thread()

        logger.info("AutoReloadCredentialLoader initialised for company %s", self.company_name)

    # ==========================================================
    # BACKGROUND RELOAD
    # ==========================================================

    def _start_reload_thread(self):
        self._reload_thread = threading.Thread(
            target=self._reload_worker,
            daemon=True,
            name="CredentialReloadWorker",
        )
        self._reload_thread.start()

    def _reload_worker(self):
        while self._running:
            try:
                if not self._reload_queue.empty():
                    company = self._reload_queue.get_nowait()
                    self._perform_auto_reload(company)

                time.sleep(1)

            except Exception:
                logger.exception("Error in credential reload worker")
                time.sleep(5)

    def _perform_auto_reload(self, company: str):
        self.stats["reloads_attempted"] += 1

        try:
            logger.info("Auto-reloading credentials for %s", company)

            self.clear_cache(company)
            credentials = self._fetch_credentials_from_iam(company)

            if credentials and self._iam_says_expired(credentials) and not self._test_credentials(credentials):
                self._expired_until[company] = datetime.now() + timedelta(seconds=self.cache_ttl)
                self.stats["reloads_failed"] += 1
                self.stats["last_failure"] = datetime.now()
                logger.error("Auto-reload: the key for %s is expired and rejected by IBM", company)

            elif credentials:
                if self._test_credentials(credentials):
                    credentials["_test_status"] = "success"
                    self._cache_credentials(company, credentials)
                    self.stats["reloads_successful"] += 1
                    self.stats["last_success"] = datetime.now()
                    self._update_iam_test_status(company, "success")
                else:
                    credentials["_test_status"] = "failed"
                    self._cache_credentials(company, credentials)
                    self.stats["reloads_failed"] += 1
                    self.stats["last_failure"] = datetime.now()
                    logger.error("Auto-reloaded credentials failed their test for %s", company)
                    self._update_iam_test_status(company, "failed")
            else:
                self.stats["reloads_failed"] += 1
                self.stats["last_failure"] = datetime.now()
                logger.error("Auto-reload failed: could not fetch credentials for %s", company)
                self._update_iam_test_status(company, "failed")

        except Exception:
            self.stats["reloads_failed"] += 1
            self.stats["last_failure"] = datetime.now()
            logger.exception("Auto-reload error for %s", company)
            self._update_iam_test_status(company, "failed")

    def _update_iam_test_status(self, company: str, status: str):
        """Report the outcome back to IAM - only when IAM_REPORT_TEST_STATUS is true"""
        if not self.report_test_status:
            return

        import requests

        try:
            response = requests.post(
                f"{self.base_url}/api/watson-keys/company/{company}/test-status",
                json={"test_status": status},
                timeout=5,
            )

            if response.status_code != 200:
                logger.warning("Failed to update IAM test_status: %s", response.status_code)

        except Exception:
            logger.exception("Error updating IAM test_status")

    def _test_credentials(self, credentials: Dict) -> bool:
        """True if IBM Cloud issues a token for this API key"""
        import requests

        try:
            response = requests.post(
                self.IBM_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": credentials.get("api_key"),
                },
                timeout=10,
            )

            return response.status_code == 200

        except Exception:
            logger.exception("Credential test failed")
            return False

    # ==========================================================
    # FETCHING
    # ==========================================================

    def get_watson_credentials_with_retry(self, company_name: Optional[str] = None) -> Optional[Dict]:
        """Credentials for the company, from cache or IAM, tested on fetch"""
        company = company_name or self.company_name
        self.stats["total_requests"] += 1

        # IAM said this key had expired, recently. Asking again within the
        # cache TTL would cost every question an IAM round trip for nothing.
        if datetime.now() < self._expired_until.get(company, datetime.min):
            return None

        if self._is_cached_valid(company):
            self.stats["cache_hits"] += 1
            cached = self._credentials_cache[company]

            if cached.get("_test_status") == "failed":
                logger.warning("Cached credentials for %s are marked failed; triggering reload", company)
                self.trigger_auto_reload(company)

            return cached

        for attempt in range(self.max_retries):
            try:
                credentials = self._fetch_credentials_from_iam(company)

                if credentials and self._iam_says_expired(credentials):
                    # IAM's expiry fields are not always updated when a key is
                    # replaced, so IBM decides. Either way there is no retry:
                    # a rejected expired key will not start working in five
                    # seconds.
                    if self._test_credentials(credentials):
                        logger.warning(
                            "IAM marks the watsonx key for %s expired (%s), but IBM Cloud "
                            "accepts it - IAM's record is stale; using the key",
                            company, credentials.get("expiration_date"),
                        )
                        credentials["_test_status"] = "success"
                        credentials["_iam_marked_expired"] = True
                        self._cache_credentials(company, credentials)
                        self._failure_count[company] = 0
                        self.last_error = None
                        return credentials

                    self._expired_until[company] = datetime.now() + timedelta(seconds=self.cache_ttl)
                    self.last_error = (
                        f"IAM reports the watsonx API key for {company} expired"
                        f" on {credentials.get('expiration_date') or 'an unknown date'},"
                        f" and IBM Cloud rejects it"
                    )
                    logger.error(self.last_error)
                    return None

                if credentials:
                    if self._test_credentials(credentials):
                        credentials["_test_status"] = "success"
                        self._cache_credentials(company, credentials)
                        self._failure_count[company] = 0
                        self.last_error = None
                        return credentials

                    self.last_error = "IBM Cloud rejected the API key from IAM"

                    credentials["_test_status"] = "failed"
                    self._cache_credentials(company, credentials)
                    self._failure_count[company] = self._failure_count.get(company, 0) + 1

                    if self._failure_count[company] >= 2:
                        logger.warning(
                            "Credentials failed %s times; triggering auto-reload",
                            self._failure_count[company],
                        )
                        self.trigger_auto_reload(company)

            except Exception:
                logger.exception("Credential attempt %s failed for %s", attempt + 1, company)

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        self.last_error = self.last_error or f"Could not load credentials for {company} from IAM"
        logger.error("All credential attempts failed for %s", company)
        return None

    @staticmethod
    def _iam_says_expired(credentials: Dict) -> bool:
        return bool(credentials.get("expired")) or str(credentials.get("status", "")).lower() == "expired"

    def _fetch_credentials_from_iam(self, company: str) -> Optional[Dict]:
        if not self.base_url:
            logger.error("IAM_MANAGEMENT_URL is not set")
            return None

        import requests

        try:
            response = requests.get(
                f"{self.base_url}/api/watson-credentials/company/{company}",
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success") and "data" in data:
                    return data["data"]
                self.last_error = f"IAM returned no credentials for {company}"
                logger.error("IAM returned 200 without credentials for %s", company)

            elif response.status_code == 404:
                logger.error("Company '%s' not found in IAM", company)

            else:
                logger.error("IAM API error: %s", response.status_code)

        except Exception:
            logger.exception("Error fetching credentials from IAM")

        return None

    def trigger_auto_reload(self, company: Optional[str] = None):
        company = company or self.company_name
        self._reload_queue.put(company)
        logger.info("Auto-reload triggered for %s", company)

    def check_and_auto_reload(self, company: Optional[str] = None) -> bool:
        """
        Trigger a reload if the cached credentials are known to be bad.

        Unlike QUOT, this does not call IBM to re-test on every invocation.
        Returns True if a reload was triggered.
        """
        company = company or self.company_name
        credentials = self._credentials_cache.get(company)

        if credentials and credentials.get("_test_status") == "failed":
            logger.info("Credentials for %s are marked failed; triggering auto-reload", company)
            self.trigger_auto_reload(company)
            return True

        return False

    # ==========================================================
    # CACHE
    # ==========================================================

    def _cache_credentials(self, company: str, credentials: Dict):
        now = datetime.now()
        credentials["_cached_at"] = now.isoformat()
        credentials["_cache_expiry"] = (now + timedelta(seconds=self.cache_ttl)).isoformat()

        with self._lock:
            self._credentials_cache[company] = credentials

    def _is_cached_valid(self, company: str) -> bool:
        cached = self._credentials_cache.get(company)

        if not cached or not cached.get("_cache_expiry"):
            return False

        try:
            return datetime.now() < datetime.fromisoformat(cached["_cache_expiry"])
        except ValueError:
            return False

    def clear_cache(self, company: Optional[str] = None):
        with self._lock:
            if company:
                self._credentials_cache.pop(company, None)
                self._expired_until.pop(company, None)
            else:
                self._credentials_cache.clear()
                self._expired_until.clear()

    def get_stats(self) -> Dict:
        return {
            **{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.stats.items()},
            "cache_size": len(self._credentials_cache),
            "failure_counts": dict(self._failure_count),
            "queue_size": self._reload_queue.qsize(),
            "uptime_seconds": int((datetime.now() - self.stats["start_time"]).total_seconds()),
        }

    def shutdown(self):
        self._running = False
        if self._reload_thread:
            self._reload_thread.join(timeout=5)
