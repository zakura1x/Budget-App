"""
API v1 - mounted at API_PREFIX (/ZBDGT/api/v1).

Each phase adds its endpoint modules here.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, settings

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(settings.router)
