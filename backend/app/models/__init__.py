"""Import all model modules so Base.metadata is complete for Alembic."""
from app.models import access, catalogue, documents, orders, organization  # noqa: F401
from app.models.base import Base  # noqa: F401
