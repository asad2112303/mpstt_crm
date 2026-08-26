"""Aggregate /api/v1 router. Module routers register here as they are built."""
from fastapi import APIRouter

from app.api.v1 import (
    admin_users,
    auth,
    catalogue,
    customers,
    deliveries,
    documents,
    imports,
    inventory,
    invoices,
    orders,
    organizations,
    payments,
    prospects,
    quotations,
    reports,
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
api_router.include_router(invoices.router)
api_router.include_router(deliveries.router)
api_router.include_router(payments.router)
api_router.include_router(reports.router)
api_router.include_router(imports.router)
