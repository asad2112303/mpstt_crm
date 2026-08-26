"""Aggregate /api/v1 router. Module routers register here as they are built."""
from fastapi import APIRouter

from app.api.v1 import (
    admin_users,
    auth,
    catalogue,
    customers,
    documents,
    inventory,
    orders,
    organizations,
    prospects,
    quotations,
    settings,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin_users.router)
api_router.include_router(catalogue.router)
api_router.include_router(prospects.router)
api_router.include_router(organizations.router)
api_router.include_router(customers.router)
api_router.include_router(documents.router)
api_router.include_router(settings.router)
api_router.include_router(quotations.router)
api_router.include_router(orders.router)
api_router.include_router(inventory.router)
