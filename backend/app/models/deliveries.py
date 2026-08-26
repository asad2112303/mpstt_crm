"""M8: deliveries, delivery items, proof of delivery.

Delivery/POD answers WHAT PHYSICALLY MOVED and who received it —
separate from the invoice (what is owed).
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditedMixin, Base, UUIDPKMixin

DELIVERY_STATUSES = ("draft", "dispatched", "delivered", "cancelled")


class Delivery(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint(f"status IN {DELIVERY_STATUSES!r}", name="status_valid"),
        Index("ix_deliveries_order", "sales_order_id", "status"),
        Index("ix_deliveries_status_scheduled", "status", "scheduled_date"),
    )

    challan_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_branches.id", ondelete="RESTRICT")
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="draft")
    scheduled_date: Mapped[datetime | None] = mapped_column()
    dispatched_at: Mapped[datetime | None] = mapped_column()
    delivered_at: Mapped[datetime | None] = mapped_column()
    delivery_person: Mapped[str | None] = mapped_column(String(150))
    vehicle: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    challan_pdf_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    items: Mapped[list["DeliveryItem"]] = relationship(
        back_populates="delivery", lazy="selectin", cascade="all, delete-orphan"
    )
    pod: Mapped["ProofOfDelivery | None"] = relationship(
        back_populates="delivery", lazy="selectin", uselist=False,
        cascade="all, delete-orphan",
    )


class DeliveryItem(Base, UUIDPKMixin):
    __tablename__ = "delivery_items"
    __table_args__ = (
        CheckConstraint("dispatched_quantity >= 0", name="dispatched_non_negative"),
        CheckConstraint("delivered_quantity >= 0", name="delivered_non_negative"),
        CheckConstraint("rejected_quantity >= 0", name="rejected_non_negative"),
        CheckConstraint(
            "delivered_quantity + rejected_quantity <= dispatched_quantity",
            name="delivered_within_dispatched",
        ),
    )

    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sales_order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    description_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    uom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    dispatched_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    delivered_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, server_default=text("0")
    )
    rejection_remarks: Mapped[str | None] = mapped_column(Text)

    delivery: Mapped[Delivery] = relationship(back_populates="items")


class ProofOfDelivery(Base, UUIDPKMixin):
    """POD gate evidence: receiver identity + signed challan/signature."""

    __tablename__ = "proof_of_delivery"

    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    receiver_name: Mapped[str] = mapped_column(String(150), nullable=False)
    receiver_designation: Mapped[str | None] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    signed_challan_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    signature_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    photo_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

    delivery: Mapped[Delivery] = relationship(back_populates="pod")
