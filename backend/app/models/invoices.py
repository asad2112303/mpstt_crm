"""M7: invoices. What is OWED — separate from what was delivered (M8)."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditedMixin, Base, UUIDPKMixin

# Stored statuses. partially_paid/paid/overdue are DERIVED from allocations
# and the due date — never stored, never manually editable.
INVOICE_STATUSES = ("draft", "issued", "cancelled")


class Invoice(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(f"status IN {INVOICE_STATUSES!r}", name="status_valid"),
        CheckConstraint("origin IN ('system','migration')", name="origin_valid"),
        Index("ix_invoices_status_due", "status", "due_date"),
        Index("ix_invoices_org", "organization_id"),
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

    invoice: Mapped[Invoice] = relationship(back_populates="items")
