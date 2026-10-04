"""Rate quotations — a published price list, not a priced order.

Deliberately separate from M5 quotations. A quotation prices a specific order:
every line has a quantity and the document totals. A rate quotation answers
"what do you charge for this?" — products and their per-unit rates, nothing to
add up, and no path to an order. Mixing the two would make "a quotation always
has quantities and a total" a conditional rather than an invariant.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
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

RATE_QUOTE_STATUSES = ("issued", "cancelled")


class RateQuotation(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "rate_quotations"
    __table_args__ = (
        CheckConstraint(f"status IN {RATE_QUOTE_STATUSES!r}", name="status_valid"),
        Index("ix_rate_quotations_date", "quote_date"),
        Index("ix_rate_quotations_org", "organization_id"),
    )

    quotation_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # A saved customer, or just a name — a rate list is often handed over
    # before anyone is in the system.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    customer_name: Mapped[str | None] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(150))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    quote_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="issued")
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    pdf_context: Mapped[dict | None] = mapped_column(JSONB)

    items: Mapped[list["RateQuotationItem"]] = relationship(
        back_populates="quotation", lazy="selectin",
        order_by="RateQuotationItem.sort_order", cascade="all, delete-orphan",
    )


class RateQuotationItem(Base, UUIDPKMixin):
    __tablename__ = "rate_quotation_items"
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="price_non_negative"),
        Index("ix_rate_quotation_items_parent", "rate_quotation_id"),
    )

    rate_quotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rate_quotations.id", ondelete="CASCADE"), nullable=False
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
    uom_code: Mapped[str] = mapped_column(String(20), nullable=False)
    # A rate per unit. There is no quantity and no line total by design.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    quotation: Mapped[RateQuotation] = relationship(back_populates="items")
