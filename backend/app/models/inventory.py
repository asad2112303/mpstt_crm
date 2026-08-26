"""M6: warehouses, stock balances, reservations, movements."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin

RESERVATION_STATUSES = ("active", "released", "fulfilled")
MOVEMENT_TYPES = (
    "opening", "adjustment", "delivery_out", "delivery_reversal", "receipt_in",
)


class Warehouse(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "warehouses"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class StockBalance(Base):
    """Available = on_hand - reserved; both constrained non-negative."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="on_hand_non_negative"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
        CheckConstraint("reserved <= on_hand", name="reserved_within_on_hand"),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), primary_key=True
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), primary_key=True
    )
    on_hand: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )
    reserved: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )
    version: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=text("now()"), nullable=False
    )


class StockReservation(Base, UUIDPKMixin):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint(f"status IN {RESERVATION_STATUSES!r}", name="status_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_reservations_order_item", "sales_order_item_id", "status"),
    )

    sales_order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False
    )
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column()
    fulfilled_at: Mapped[datetime | None] = mapped_column()


class StockMovement(Base, UUIDPKMixin):
    """Append-only signed on-hand changes; reversals are new entries."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(f"movement_type IN {MOVEMENT_TYPES!r}", name="type_valid"),
        CheckConstraint("quantity <> 0", name="quantity_non_zero"),
        Index("ix_movements_variant_wh_time", "product_variant_id", "warehouse_id", "movement_at"),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(  # signed: +in / -out
        Numeric(14, 3), nullable=False
    )
    movement_type: Mapped[str] = mapped_column(String(25), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    reference_id: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    movement_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
