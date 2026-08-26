"""M9: payments, allocations, receipts."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

PAYMENT_STATUSES = ("recorded", "partially_allocated", "allocated", "reversed")
PAYMENT_METHODS = ("cash", "bank_transfer", "cheque", "online", "other")


class Payment(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(f"status IN {PAYMENT_STATUSES!r}", name="status_valid"),
        CheckConstraint(f"method IN {PAYMENT_METHODS!r}", name="method_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_payments_org", "organization_id", "status"),
    )

    payment_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(150))
    proof_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(25), nullable=False, server_default="recorded")
    notes: Mapped[str | None] = mapped_column(Text)
    reversal_reason: Mapped[str | None] = mapped_column(Text)
    reversed_at: Mapped[datetime | None] = mapped_column()
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        back_populates="payment", lazy="selectin", cascade="all, delete-orphan"
    )
    receipt: Mapped["Receipt | None"] = relationship(
        back_populates="payment", lazy="selectin", uselist=False
    )


class PaymentAllocation(Base, UUIDPKMixin):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("allocated_amount > 0", name="amount_positive"),
        UniqueConstraint("payment_id", "invoice_id", name="uq_allocation_payment_invoice"),
        Index("ix_allocations_invoice", "invoice_id"),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="allocations")


class Receipt(Base, UUIDPKMixin):
    __tablename__ = "receipts"

    receipt_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    issued_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    pdf_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    payment: Mapped[Payment] = relationship(back_populates="receipt")
