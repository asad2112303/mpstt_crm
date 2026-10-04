"""Rate quotations: a price list, with no quantities and no total

A customer asking "what do you charge for waste bags?" wants rates, not a
priced order. The M5 quotation cannot answer that — every line carries a
quantity and the document ends in a TOTAL AMOUNT band — so this is its own
small thing rather than a conditional bolted onto the sales pipeline.

A rate quotation names products and what each one costs per unit. There is
no quantity to enter and nothing to total, and it never converts to an order:
it is a published price, and the customer orders afterwards in the usual way.

Revision ID: 0017_rate_quotations
Revises: 0016_billing_seed
Create Date: 2026-10-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = '0017_rate_quotations'
down_revision: str | None = '0016_billing_seed'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_quotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("quotation_number", sa.String(20), nullable=False, unique=True),
        # Either a saved customer or just a name typed on the day — a rate
        # list is often handed over before anyone is in the system.
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("crm.organizations.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("contact_person", sa.String(150), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("quote_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="issued"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        # Frozen at issue, exactly like the invoice: the PDF never changes
        # because a product was renamed or repriced afterwards.
        sa.Column("pdf_context", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('issued','cancelled')", name="status_valid"),
        schema="crm",
    )
    op.create_index("ix_rate_quotations_date", "rate_quotations",
                    ["quote_date"], schema="crm", postgresql_using="btree")
    op.create_index("ix_rate_quotations_org", "rate_quotations",
                    ["organization_id"], schema="crm")

    op.create_table(
        "rate_quotation_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("rate_quotation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("crm.rate_quotations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("crm.products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_variant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("crm.product_variants.id", ondelete="RESTRICT"), nullable=False),
        # Frozen description and specification, so a later catalogue edit never
        # rewrites a rate that has already been quoted.
        sa.Column("description_snapshot", sa.Text(), nullable=False),
        sa.Column("specification_snapshot", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("uom_code", sa.String(20), nullable=False),
        # The whole point: a rate per unit. No quantity, no line total.
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("unit_price >= 0", name="price_non_negative"),
        schema="crm",
    )
    op.create_index("ix_rate_quotation_items_parent", "rate_quotation_items",
                    ["rate_quotation_id"], schema="crm")


def downgrade() -> None:
    op.drop_table("rate_quotation_items", schema="crm")
    op.drop_table("rate_quotations", schema="crm")
