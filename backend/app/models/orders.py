"""Sales orders (created in M4 conversion; workflow/inventory in M6)."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditedMixin, Base, UUIDPKMixin

ORDER_STATUSES = (
    "draft", "confirmed", "preparing", "ready",
    "partially_delivered", "fully_delivered", "completed", "cancelled",
)
# Delivery-driven statuses are derived, never PATCHed by hand.
DELIVERY_DERIVED_STATUSES = ("partially_delivered", "fully_delivered")


class SalesOrder(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "sales_orders"
    __table_args__ = (
        CheckConstraint(f"status IN {ORDER_STATUSES!r}", name="status_valid"),
        Index("ix_sales_orders_org_status", "organization_id", "status"),
    )

    order_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_branches.id", ondelete="RESTRICT")
    )
    # FK to crm.quotations is added by the M5 migration (table exists later).
    source_quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_direct_po: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    customer_po_number: Mapped[str | None] = mapped_column(String(100))
    customer_po_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    order_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(25), nullable=False, server_default="draft")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    grand_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="order", lazy="selectin", order_by="SalesOrderItem.sort_order",
        cascade="all, delete-orphan",
    )


class SalesOrderItem(Base, UUIDPKMixin):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("discount_percent >= 0 AND discount_percent <= 100", name="discount_range"),
    )

    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    # Frozen at order time — catalogue edits never rewrite ordered history.
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

    order: Mapped[SalesOrder] = relationship(back_populates="items")
