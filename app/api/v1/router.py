"""
API v1 - mounted at API_PREFIX (/ZBDGT/api/v1).

Each phase adds its endpoint modules here.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import accounts, auth, categories, health, settings, transactions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(accounts.router)
api_router.include_router(categories.router)
api_router.include_router(transactions.router)
