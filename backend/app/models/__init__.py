"""Import all model modules so Base.metadata is complete for Alembic."""
from app.models import access, catalogue, documents, inventory, orders, organization, quotes  # noqa: F401
from app.models.base import Base  # noqa: F401
