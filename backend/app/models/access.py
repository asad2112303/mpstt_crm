"""M1 tables: user profiles, company settings, numbering, audit, idempotency."""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserProfile(Base, TimestampMixin):
    """Application profile for a Supabase Auth user.

    ``id`` mirrors ``auth.users(id)``. The FK is added in the migration only
    when the auth schema exists (managed Supabase); local dev has no auth schema.
    """

    __tablename__ = "user_profiles"
    __table_args__ = (CheckConstraint("role IN ('admin','user')", name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="user")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column()


class CompanySettings(Base, TimestampMixin):
    """Singleton row (id = 1) with MPSTT identity used on official documents."""

    __tablename__ = "company_settings"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(255))
    ntn: Mapped[str | None] = mapped_column(String(50))
    strn: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    bank_details: Mapped[str | None] = mapped_column(Text)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="PKR")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, server_default="Asia/Karachi")
    default_payment_terms_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    quotation_terms: Mapped[str | None] = mapped_column(Text)
    document_footer: Mapped[str | None] = mapped_column(Text)
    logo_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class NumberSequence(Base):
    """Concurrency-safe document numbering. Allocation locks the row FOR UPDATE."""

    __tablename__ = "number_sequences"

    document_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    padding: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("4"))


class AuditLog(Base):
    """Append-only audit trail. A DB trigger rejects UPDATE/DELETE."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80))
    old_data: Mapped[dict | None] = mapped_column(JSONB)
    new_data: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(60))
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class IdempotencyKey(Base):
    """Stored responses for high-impact POST actions."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "action", "idempotency_key", name="uq_idem_user_action_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
