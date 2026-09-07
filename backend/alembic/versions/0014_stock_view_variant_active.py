"""Expose variant is_active on the stock view

Retiring a variant left an empty row on the balances list forever, because
the view had no way to tell an active line from a retired one. The endpoint
now hides retired variants that hold no stock.

Revision ID: 0014_stock_view_active
Revises: 0013_pdf_snapshots
Create Date: 2026-09-07
"""
from collections.abc import Sequence

from alembic import op

revision: str = '0014_stock_view_active'
down_revision: str | None = '0013_pdf_snapshots'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = """
            sb.warehouse_id,
            w.code AS warehouse_code,
            sb.product_variant_id,
            p.sku,
            p.name AS product_name,
            pv.variant_name,
            pv.variant_code,
            u.code AS uom_code,
            sb.on_hand,
            sb.reserved,
            (sb.on_hand - sb.reserved) AS available,
            sb.updated_at"""

FROM_CLAUSE = """
        FROM crm.stock_balances sb
        JOIN crm.warehouses w ON w.id = sb.warehouse_id
        JOIN crm.product_variants pv ON pv.id = sb.product_variant_id
        JOIN crm.products p ON p.id = pv.product_id
        JOIN crm.units_of_measure u ON u.id = pv.uom_id;"""


def upgrade() -> None:
    # CREATE OR REPLACE only permits appending columns, so is_active goes last.
    op.execute(f"""
        CREATE OR REPLACE VIEW crm.v_stock_available AS
        SELECT{COLUMNS},
            pv.is_active AS variant_is_active{FROM_CLAUSE}
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS crm.v_stock_available")
    op.execute(f"""
        CREATE OR REPLACE VIEW crm.v_stock_available AS
        SELECT{COLUMNS}{FROM_CLAUSE}
    """)
