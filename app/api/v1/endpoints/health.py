"""
GET {API_PREFIX}/health - the page IIS warms the app with (web.config,
applicationInitialization), and the first thing to open after a deploy.

Reports whether the database is reachable, whether schema ZBDGT exists, and
whether the master key loaded and passed its self-test. Unauthenticated, so it
says yes or no and nothing else: no server name, no driver error, no key
version, no fingerprint. 200 when everything is up, 503 when anything is not.

The database answer is cached for a few seconds so that an unauthenticated
caller cannot turn this endpoint into a way to open connections to a shared
company server as fast as they can send requests.
"""

import time

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.crypto.self_test import master_key_loaded
from app.db.connection import check_database

router = APIRouter(tags=["health"])

_DB_CACHE_SECONDS = 10.0
_db_cache = {"at": 0.0, "result": None}


async def _database_status() -> dict:
    now = time.monotonic()
    if _db_cache["result"] is None or now - _db_cache["at"] > _DB_CACHE_SECONDS:
        _db_cache["result"] = await run_in_threadpool(check_database)
        _db_cache["at"] = now
    return _db_cache["result"]


@router.get("/health")
async def health() -> JSONResponse:
    database = await _database_status()
    encryption = {"master_key_loaded": master_key_loaded()}
    healthy = database["reachable"] and database["schema_present"] and encryption["master_key_loaded"]
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "checks": {"database": database, "encryption": encryption},
        },
    )
