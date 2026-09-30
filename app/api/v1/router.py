"""
API v1 - mounted at API_PREFIX (/ZBDGT/api/v1).

Each phase adds its endpoint modules here.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    accounts,
    admin,
    assistant,
    attachments,
    auth,
    backups,
    budgets,
    data,
    goals,
    calendar,
    categories,
    health,
    projection,
    recurring,
    security,
    settings,
    statements,
    stats,
    subscriptions,
    tags,
    transactions,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(accounts.router)
api_router.include_router(statements.router)
api_router.include_router(categories.router)
api_router.include_router(tags.router)
api_router.include_router(transactions.router)
api_router.include_router(budgets.router)
api_router.include_router(calendar.router)
api_router.include_router(stats.router)
api_router.include_router(recurring.router)
api_router.include_router(subscriptions.router)
api_router.include_router(projection.router)
api_router.include_router(attachments.router)
api_router.include_router(backups.router)
api_router.include_router(data.router)
api_router.include_router(goals.router)
api_router.include_router(security.router)
api_router.include_router(admin.router)
api_router.include_router(assistant.router)
