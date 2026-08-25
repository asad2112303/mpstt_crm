"""Baseline: crm schema + required extensions.

Revision ID: 0001_baseline
Revises:
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS crm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # The crm schema is dropped only when every module migration is reverted.
    op.execute("DROP SCHEMA IF EXISTS crm CASCADE")
