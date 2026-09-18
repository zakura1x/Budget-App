"""
Budget App - FastAPI entry point.

Startup order is the design, not an accident (ARCHITECTURE.md section 2):

  1. Settings load at import - a missing, short or malformed master key raises
     ConfigurationError here and the process never serves a request.
  2. Logging is configured with the redaction filter before anything else can
     log.
  3. (lifespan) The encryption self-test runs. A key that parses but does not
     round-trip also stops startup.
  4. (lifespan) The database and schema ZBDGT are checked. A failure here is
     logged and reported by /health, but does not stop the app: the database
     is shared infrastructure that comes back on its own, and a process that
     refused to start would only turn "database down" into "502 from IIS".
  5. Static files, the API router and the SPA shell are mounted.

Middleware, outermost first: CORS (development only) -> SecurityHeaders ->
RateLimit -> Logging -> Auth.
"""

import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings  # 1. hard-fails on a bad master key
from app.core.logging_config import setup_logging

setup_logging()  # 2. redaction installed before anything else logs

from app.api.v1.router import api_router  # noqa: E402
from app.core.crypto.keyring import get_master_keyring  # noqa: E402
from app.core.crypto.self_test import run_self_test  # noqa: E402
from app.core.exceptions import setup_exception_handlers  # noqa: E402
from app.core.middleware.auth_middleware import AuthMiddleware  # noqa: E402
from app.core.middleware.logging_middleware import LoggingMiddleware  # noqa: E402
from app.core.middleware.rate_limit import RateLimitMiddleware  # noqa: E402
from app.core.middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402
from app.db.connection import check_database, dispose_engine  # noqa: E402
from app.services.backup_service.scheduler import get_scheduler  # noqa: E402 - registers the after-commit trigger (DAT-08)
from app.web.router import STATIC_DIR, router as web_router  # noqa: E402

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s v%s (%s) at %s", settings.APP_NAME, settings.APP_VERSION,
        settings.ENVIRONMENT, settings.BASE_URL_CLEAN,
    )

    run_self_test(get_master_keyring())  # 3. raises -> startup aborts

    status = await run_in_threadpool(check_database)  # 4.
    if not status["reachable"]:
        logger.error("Database unreachable at startup - /health will report degraded")
    elif not status["schema_present"]:
        logger.error(
            "Schema %s does not exist - run `alembic upgrade head`", settings.DB_SCHEMA
        )
    else:
        logger.info("Database reachable, schema %s present", settings.DB_SCHEMA)

    yield

    # Nothing to zero here: the session keyring lives in memory and dies with
    # the process. Dispose the pool so IIS recycles do not leave connections.
    # A pending automatic backup is dropped: the next sign-in catches up (DAT-08).
    get_scheduler().cancel_all()
    dispose_engine()
    logger.info("Shutdown complete")


docs_enabled = settings.DEBUG and not settings.is_production
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=f"{settings.API_PREFIX}/docs" if docs_enabled else None,
    swagger_ui_oauth2_redirect_url=None,
    redoc_url=None,
    openapi_url=f"{settings.API_PREFIX}/openapi.json" if docs_enabled else None,
)

# Added innermost-first: Starlette makes the LAST added middleware the outermost.
# Resulting order, outermost first: CORS -> SecurityHeaders -> RateLimit ->
# Logging -> Auth. SecurityHeaders sits outside RateLimit so a 429 still
# carries the headers.
app.add_middleware(AuthMiddleware, api_prefix=settings.API_PREFIX)
app.add_middleware(LoggingMiddleware, api_prefix=settings.API_PREFIX)
app.add_middleware(RateLimitMiddleware, api_prefix=settings.API_PREFIX)
app.add_middleware(
    SecurityHeadersMiddleware,
    api_prefix=settings.API_PREFIX,
    csp_exempt_paths=(f"{settings.API_PREFIX}/docs", f"{settings.API_PREFIX}/openapi.json") if docs_enabled else (),
    worker_paths=(f"{settings.BASE_URL_CLEAN}/sw.js",),
)
if not settings.is_production:
    # Only the Vite dev server needs this. In production the bundle and the API
    # share an origin and CORS does not apply.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Requested-With"],
    )

setup_exception_handlers(app)


class _AssetStaticFiles(StaticFiles):
    """
    Hashed bundle files never change under the same name, so they may be
    cached for a year. Anything else (icons, the manifest) is revalidated.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.startswith("dist/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


# The bundled font (the redesign of 2026-09-18). Python 3.11 on Windows has no
# type for .woff2 and would serve it as text/plain.
mimetypes.add_type("font/woff2", ".woff2")

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount(f"{settings.BASE_URL_CLEAN}/static", _AssetStaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(api_router, prefix=settings.API_PREFIX)
app.include_router(web_router)  # last: its fallback route catches /ZBDGT/*


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=settings.DEBUG, workers=1)
