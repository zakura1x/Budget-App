"""
API v1 - mounted at API_PREFIX (/ZBDGT/api/v1).

Phase 1 has only /health. Each later phase adds its endpoint module here.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router)
