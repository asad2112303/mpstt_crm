"""Import all model modules so Base.metadata is complete for Alembic."""
from app.models import (  # noqa: F401
    access,
    catalogue,
    deliveries,
    documents,
    inventory,
    invoices,
    orders,
    organization,
    payments,
    quotes,
)
from app.models.base import Base  # noqa: F401
