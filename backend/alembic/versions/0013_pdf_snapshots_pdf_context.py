"""Freeze document render contexts on the record

Issuing a document used to depend on uploading the rendered PDF to object
storage; an unreachable bucket made the whole operation fail. The frozen
context is stored on the record instead, and the PDF is rendered on demand.

Revision ID: 0013_pdf_snapshots
Revises: 0012_m12_imports
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '0013_pdf_snapshots'
down_revision: str | None = '0012_m12_imports'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("quotations", "invoices", "receipts")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("pdf_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            schema="crm",
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "pdf_context", schema="crm")
