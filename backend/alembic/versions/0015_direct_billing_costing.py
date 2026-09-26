"""Direct billing (Quick Bill / Sell from Stock) and cost-of-goods tracking

Adds a second, parallel way to sell. The existing path — quotation, order,
delivery, invoice — is untouched: those invoices still carry is_direct=false
and stock still leaves at delivery dispatch. A direct invoice instead deducts
stock when it is finalized, recorded as an 'invoice_out' movement, so the two
paths can never double-count the same stock.

Also introduces costing, which the schema had nowhere to put: a moving
weighted average per (warehouse, variant), the cost of each receipt, and the
cost frozen onto every invoice line at finalize. Lines with no cost available
are marked 'missing' rather than assumed zero, so gross profit is never
inflated.

Revision ID: 0015_direct_billing
Revises: 0014_stock_view_active
Create Date: 2026-09-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0015_direct_billing'
down_revision: str | None = '0014_stock_view_active'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOVEMENT_TYPES_OLD = "('opening', 'adjustment', 'delivery_out', 'delivery_reversal', 'receipt_in')"
MOVEMENT_TYPES_NEW = (
    "('opening', 'adjustment', 'delivery_out', 'delivery_reversal', 'receipt_in', "
    "'invoice_out', 'invoice_return')"
)


def upgrade() -> None:
    # ---- catalogue: what is tracked, what it costs, what it normally sells for ----
    op.add_column(
        "products",
        sa.Column("track_stock", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema="crm",
    )
    # Products that existed before direct billing are all stock-tracked; only
    # products created during Quick Bill default to untracked.
    op.add_column(
        "products",
        sa.Column("default_sale_price", sa.Numeric(14, 2), nullable=True),
        schema="crm",
    )
    op.add_column(
        "products",
        sa.Column("default_purchase_cost", sa.Numeric(14, 2), nullable=True),
        schema="crm",
    )
    op.add_column(
        "products",
        sa.Column(
            "created_via", sa.String(15), nullable=False, server_default="catalogue"
        ),
        schema="crm",
    )
    op.create_check_constraint(
        "created_via_valid", "products",
        "created_via IN ('catalogue','quick_bill','import')", schema="crm",
    )
    op.create_index(
        "ix_products_track_stock", "products", ["track_stock", "is_active"], schema="crm"
    )

    op.add_column(
        "product_variants",
        sa.Column("reorder_level", sa.Numeric(14, 3), nullable=True),
        schema="crm",
    )
    # Fallback cost for untracked (Quick Bill) variants, which hold no balance
    # row and therefore no weighted average.
    op.add_column(
        "product_variants",
        sa.Column("standard_cost", sa.Numeric(14, 4), nullable=True),
        schema="crm",
    )
    op.add_column(
        "product_variants",
        sa.Column("last_sale_price", sa.Numeric(14, 2), nullable=True),
        schema="crm",
    )

    # ---- costing on stock ----
    op.add_column(
        "stock_balances",
        sa.Column("avg_cost", sa.Numeric(14, 4), nullable=True),
        schema="crm",
    )
    op.add_column(
        "stock_movements",
        sa.Column("unit_cost", sa.Numeric(14, 4), nullable=True),
        schema="crm",
    )
    op.drop_constraint("ck_stock_movements_type_valid", "stock_movements", schema="crm")
    op.create_check_constraint(
        "type_valid", "stock_movements",
        f"movement_type IN {MOVEMENT_TYPES_NEW}", schema="crm",
    )

    # ---- walk-in customer ----
    # A reserved system organization rather than a nullable invoice.organization_id:
    # every existing join, report and receivables query keeps working unchanged.
    op.add_column(
        "organizations",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="crm",
    )
    op.execute(
        """
        INSERT INTO crm.organizations
            (org_code, name, org_type, lifecycle_status, is_active, is_system, notes)
        VALUES
            ('WALK-IN', 'Walk-in Customer', 'other', 'customer', true, true,
             'Reserved system row for counter sales. Do not edit or delete.')
        ON CONFLICT (org_code) DO NOTHING
        """
    )

    # ---- invoices: direct sale header ----
    op.add_column(
        "invoices",
        sa.Column("is_direct", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="crm",
    )
    op.add_column(
        "invoices",
        sa.Column("is_walk_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="crm",
    )
    op.add_column(
        "invoices",
        sa.Column(
            "warehouse_id", sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crm.warehouses.id", ondelete="RESTRICT"), nullable=True,
        ),
        schema="crm",
    )
    # Set exactly once when stock is deducted, so a double-click or a retry
    # after a dropped connection cannot deduct twice.
    op.add_column(
        "invoices",
        sa.Column("stock_committed_at", sa.DateTime(timezone=True), nullable=True),
        schema="crm",
    )
    op.add_column(
        "invoices",
        sa.Column("stock_reversed_at", sa.DateTime(timezone=True), nullable=True),
        schema="crm",
    )
    op.add_column("invoices", sa.Column("reference_number", sa.String(100)), schema="crm")
    op.add_column("invoices", sa.Column("contact_person", sa.String(150)), schema="crm")
    op.add_column("invoices", sa.Column("contact_phone", sa.String(50)), schema="crm")
    op.add_column("invoices", sa.Column("billing_address", sa.Text()), schema="crm")
    op.add_column("invoices", sa.Column("delivery_address", sa.Text()), schema="crm")
    op.add_column("invoices", sa.Column("walk_in_name", sa.String(200)), schema="crm")
    op.add_column("invoices", sa.Column("payment_terms_note", sa.Text()), schema="crm")

    op.add_column(
        "invoices",
        sa.Column("overall_discount_type", sa.String(10), nullable=True),
        schema="crm",
    )
    op.add_column(
        "invoices",
        sa.Column(
            "overall_discount_value", sa.Numeric(14, 2),
            nullable=False, server_default=sa.text("0"),
        ),
        schema="crm",
    )
    op.add_column(
        "invoices",
        sa.Column(
            "overall_discount_amount", sa.Numeric(14, 2),
            nullable=False, server_default=sa.text("0"),
        ),
        schema="crm",
    )
    op.add_column(
        "invoices",
        sa.Column(
            "delivery_charge", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")
        ),
        schema="crm",
    )
    op.create_check_constraint(
        "overall_discount_type_valid", "invoices",
        "overall_discount_type IS NULL OR overall_discount_type IN ('percent','amount')",
        schema="crm",
    )
    op.create_check_constraint(
        "overall_discount_non_negative", "invoices",
        "overall_discount_value >= 0 AND overall_discount_amount >= 0", schema="crm",
    )
    op.create_check_constraint(
        "delivery_charge_non_negative", "invoices", "delivery_charge >= 0", schema="crm",
    )
    op.create_index(
        "ix_invoices_direct_issued", "invoices", ["is_direct", "status"], schema="crm"
    )

    # ---- invoice lines: cost frozen at finalize ----
    op.add_column(
        "invoice_items",
        sa.Column("unit_cost", sa.Numeric(14, 4), nullable=True),
        schema="crm",
    )
    op.add_column(
        "invoice_items",
        sa.Column("cost_source", sa.String(20), nullable=True),
        schema="crm",
    )
    op.add_column(
        "invoice_items",
        sa.Column(
            "line_source", sa.String(15), nullable=False, server_default="stock"
        ),
        schema="crm",
    )
    op.create_check_constraint(
        "cost_source_valid", "invoice_items",
        "cost_source IS NULL OR cost_source IN "
        "('weighted_average','manual','product_default','missing')",
        schema="crm",
    )
    op.create_check_constraint(
        "line_source_valid", "invoice_items",
        "line_source IN ('stock','quick_bill')", schema="crm",
    )


def downgrade() -> None:
    for name in ("line_source_valid", "cost_source_valid"):
        op.drop_constraint(f"ck_invoice_items_{name}", "invoice_items", schema="crm")
    for col in ("line_source", "cost_source", "unit_cost"):
        op.drop_column("invoice_items", col, schema="crm")

    op.drop_index("ix_invoices_direct_issued", "invoices", schema="crm")
    for name in (
        "delivery_charge_non_negative",
        "overall_discount_non_negative",
        "overall_discount_type_valid",
    ):
        op.drop_constraint(f"ck_invoices_{name}", "invoices", schema="crm")
    for col in (
        "delivery_charge", "overall_discount_amount", "overall_discount_value",
        "overall_discount_type", "payment_terms_note", "walk_in_name", "delivery_address",
        "billing_address", "contact_phone", "contact_person", "reference_number",
        "stock_reversed_at", "stock_committed_at", "warehouse_id", "is_walk_in", "is_direct",
    ):
        op.drop_column("invoices", col, schema="crm")

    # Only if nothing points at it: real walk-in sales must survive a downgrade.
    op.execute(
        """
        DELETE FROM crm.organizations o
        WHERE o.org_code = 'WALK-IN' AND o.is_system
          AND NOT EXISTS (SELECT 1 FROM crm.invoices i WHERE i.organization_id = o.id)
          AND NOT EXISTS (SELECT 1 FROM crm.payments p WHERE p.organization_id = o.id)
        """
    )
    op.drop_column("organizations", "is_system", schema="crm")

    op.drop_constraint("ck_stock_movements_type_valid", "stock_movements", schema="crm")
    # Direct-sale movements are not valid under the old constraint. Reclassify
    # rather than delete: the quantities really did move, and losing them would
    # leave on-hand balances unexplainable.
    op.execute(
        """
        UPDATE crm.stock_movements
        SET movement_type = 'adjustment',
            notes = COALESCE(notes || ' ', '') || '(was ' || movement_type || ')'
        WHERE movement_type IN ('invoice_out', 'invoice_return')
        """
    )
    op.create_check_constraint(
        "type_valid", "stock_movements",
        f"movement_type IN {MOVEMENT_TYPES_OLD}", schema="crm",
    )
    op.drop_column("stock_movements", "unit_cost", schema="crm")
    op.drop_column("stock_balances", "avg_cost", schema="crm")

    for col in ("last_sale_price", "standard_cost", "reorder_level"):
        op.drop_column("product_variants", col, schema="crm")

    op.drop_index("ix_products_track_stock", "products", schema="crm")
    op.drop_constraint("ck_products_created_via_valid", "products", schema="crm")
    for col in ("created_via", "default_purchase_cost", "default_sale_price", "track_stock"):
        op.drop_column("products", col, schema="crm")
