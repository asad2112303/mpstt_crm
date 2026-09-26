"""M7: invoices. What is OWED — separate from what was delivered (M8)."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditedMixin, Base, UUIDPKMixin

# Stored statuses. partially_paid/paid/overdue are DERIVED from allocations
# and the due date — never stored, never manually editable.
INVOICE_STATUSES = ("draft", "issued", "cancelled")

# How a line was sourced. 'stock' lines move inventory on a direct invoice;
# 'quick_bill' lines never do.
LINE_SOURCES = ("stock", "quick_bill")
# Where a line's cost came from, so incomplete profit is visible rather than
# silently reported as zero cost.
COST_SOURCES = ("weighted_average", "manual", "product_default", "missing")


class Invoice(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(f"status IN {INVOICE_STATUSES!r}", name="status_valid"),
        CheckConstraint("origin IN ('system','migration')", name="origin_valid"),
        CheckConstraint(
            "overall_discount_type IS NULL OR overall_discount_type IN ('percent','amount')",
            name="overall_discount_type_valid",
        ),
        CheckConstraint(
            "overall_discount_value >= 0 AND overall_discount_amount >= 0",
            name="overall_discount_non_negative",
        ),
        CheckConstraint("delivery_charge >= 0", name="delivery_charge_non_negative"),
        Index("ix_invoices_status_due", "status", "due_date"),
        Index("ix_invoices_org", "organization_id"),
        Index("ix_invoices_direct_issued", "is_direct", "status"),
    )

    invoice_number: Mapped[str | None] = mapped_column(String(20), unique=True)  # set at issue
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="RESTRICT")
    )
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="draft")
    origin: Mapped[str] = mapped_column(String(15), nullable=False, server_default="system")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column()

    # --- direct sale (Quick Bill / Sell from Stock) ---
    # Direct invoices deduct stock when finalized. Order-driven invoices leave
    # is_direct false and stock still moves at delivery dispatch.
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_walk_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    walk_in_name: Mapped[str | None] = mapped_column(String(200))
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    # Written exactly once when stock is deducted; the guard that makes
    # finalize idempotent under double-clicks and retries.
    stock_committed_at: Mapped[datetime | None] = mapped_column()
    stock_reversed_at: Mapped[datetime | None] = mapped_column()

    reference_number: Mapped[str | None] = mapped_column(String(100))
    contact_person: Mapped[str | None] = mapped_column(String(150))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    billing_address: Mapped[str | None] = mapped_column(Text)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    payment_terms_note: Mapped[str | None] = mapped_column(Text)

    overall_discount_type: Mapped[str | None] = mapped_column(String(10))
    overall_discount_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    # The resolved cash value of the overall discount, whichever way it was entered.
    overall_discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    delivery_charge: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )

    pdf_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Frozen at issue: the exact inputs the invoice PDF is rendered from.
    pdf_context: Mapped[dict | None] = mapped_column(JSONB)

    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", lazy="selectin", order_by="InvoiceItem.sort_order",
        cascade="all, delete-orphan",
    )


class InvoiceItem(Base, UUIDPKMixin):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            f"cost_source IS NULL OR cost_source IN {COST_SOURCES!r}", name="cost_source_valid"
        ),
        CheckConstraint(f"line_source IN {LINE_SOURCES!r}", name="line_source_valid"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sales_order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    description_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    specification_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    uom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default=text("0"))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default=text("0"))
    line_net: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Cost frozen when the invoice is finalized. Later cost changes never
    # rewrite the profit on an invoice that has already been issued.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    cost_source: Mapped[str | None] = mapped_column(String(20))
    line_source: Mapped[str] = mapped_column(String(15), nullable=False, server_default="stock")

    invoice: Mapped[Invoice] = relationship(back_populates="items")
