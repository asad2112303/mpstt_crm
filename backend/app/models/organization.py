"""M2/M4 tables: organizations, branches, contacts, prospect/customer profiles,
activities, tasks, product requirement profiles, samples, organization prices."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditedMixin, Base, TimestampMixin, UUIDPKMixin

ORG_TYPES = ("hospital", "clinic", "laboratory", "pharmacy", "industry", "ngo", "government", "other")
PROSPECT_STAGES = (
    "targeted", "visited", "requirement_collected", "sample_provided",
    "quotation_sent", "negotiation", "lost", "deferred", "won",
)
# 'won' is never PATCHed manually — only first-order conversion sets it.
MANUAL_STAGES = tuple(s for s in PROSPECT_STAGES if s != "won")
ACTIVITY_TYPES = ("visit", "call", "whatsapp", "email", "meeting", "follow_up")
TASK_STATUSES = ("open", "done", "cancelled")
TASK_PRIORITIES = ("low", "normal", "high")
SAMPLE_STATUSES = ("issued", "feedback_received", "converted", "closed")
PRICE_TYPES = ("quoted", "agreed", "list")


class Organization(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(f"org_type IN {ORG_TYPES!r}", name="org_type_valid"),
        CheckConstraint("lifecycle_status IN ('prospect','customer')", name="lifecycle_valid"),
        Index("ix_organizations_name_trgm", text("name gin_trgm_ops"), postgresql_using="gin"),
        Index("ix_organizations_lifecycle", "lifecycle_status", "is_active"),
    )

    org_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    org_type: Mapped[str] = mapped_column(String(20), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="prospect")
    city: Mapped[str | None] = mapped_column(String(100))
    area: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    phone_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    ntn: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    converted_at: Mapped[datetime | None] = mapped_column()

    prospect_profile: Mapped["ProspectProfile | None"] = relationship(
        back_populates="organization", lazy="joined", uselist=False
    )
    customer_profile: Mapped["CustomerProfile | None"] = relationship(
        back_populates="organization", lazy="joined", uselist=False
    )


class OrganizationBranch(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "organization_branches"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    branch_name: Mapped[str] = mapped_column(String(150), nullable=False)
    area: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    delivery_address: Mapped[str | None] = mapped_column(Text)
    billing_address: Mapped[str | None] = mapped_column(Text)
    map_url: Mapped[str | None] = mapped_column(String(500))
    route_cluster: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class OrganizationContact(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "organization_contacts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_branches.id", ondelete="SET NULL")
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))
    phone_primary: Mapped[str | None] = mapped_column(String(50))
    phone_primary_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    phone_alt: Mapped[str | None] = mapped_column(String(50))
    whatsapp: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    preferred_channel: Mapped[str | None] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class ProspectProfile(Base, TimestampMixin):
    """One-to-one with organizations; retained after conversion for history."""

    __tablename__ = "prospect_profiles"
    __table_args__ = (
        CheckConstraint(f"stage IN {PROSPECT_STAGES!r}", name="stage_valid"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), primary_key=True
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False, server_default="targeted")
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="SET NULL")
    )
    first_contact_date: Mapped[date | None] = mapped_column(Date)
    last_activity_at: Mapped[datetime | None] = mapped_column()
    next_action_summary: Mapped[str | None] = mapped_column(String(300))
    lost_reason: Mapped[str | None] = mapped_column(Text)
    deferred_reason: Mapped[str | None] = mapped_column(Text)
    reactivation_date: Mapped[date | None] = mapped_column(Date)

    organization: Mapped[Organization] = relationship(back_populates="prospect_profile")


class CustomerProfile(Base, TimestampMixin):
    """Created only at first-order conversion (M4)."""

    __tablename__ = "customer_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), primary_key=True
    )
    customer_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_since: Mapped[date] = mapped_column(Date, nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(nullable=False, server_default=text("30"))
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    billing_notes: Mapped[str | None] = mapped_column(Text)
    purchasing_notes: Mapped[str | None] = mapped_column(Text)
    account_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")

    organization: Mapped[Organization] = relationship(back_populates="customer_profile")


class Activity(Base, UUIDPKMixin):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(f"activity_type IN {ACTIVITY_TYPES!r}", name="type_valid"),
        Index("ix_activities_org_time", "organization_id", "happened_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_contacts.id", ondelete="SET NULL")
    )
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    happened_at: Mapped[datetime] = mapped_column(nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    products_discussed: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class Task(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(f"status IN {TASK_STATUSES!r}", name="status_valid"),
        CheckConstraint(f"priority IN {TASK_PRIORITIES!r}", name="priority_valid"),
        Index("ix_tasks_assignee_status_due", "assigned_user_id", "status", "due_at"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="SET NULL")
    )
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="follow_up")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    due_at: Mapped[datetime] = mapped_column(nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, server_default="normal")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    completion_outcome: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column()
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class OrganizationProductProfile(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "organization_product_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    frequency: Mapped[str | None] = mapped_column(String(20))  # weekly|monthly|quarterly|adhoc
    min_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    max_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="RESTRICT")
    )
    current_supplier: Mapped[str | None] = mapped_column(String(200))
    current_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    specification_notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class Sample(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "samples"
    __table_args__ = (
        CheckConstraint(f"status IN {SAMPLE_STATUSES!r}", name="status_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="RESTRICT")
    )
    issued_at: Mapped[datetime] = mapped_column(nullable=False)
    receiver_name: Mapped[str | None] = mapped_column(String(150))
    feedback_due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="issued")
    feedback: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class OrganizationPrice(Base, UUIDPKMixin):
    """Customer/prospect-specific price history. Never overwritten — expired."""

    __tablename__ = "organization_prices"
    __table_args__ = (
        CheckConstraint(f"price_type IN {PRICE_TYPES!r}", name="price_type_valid"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        Index("ix_org_prices_lookup", "organization_id", "product_id", "product_variant_id",
              "effective_from"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT")
    )
    price_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="quoted")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="RESTRICT")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_reference: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
