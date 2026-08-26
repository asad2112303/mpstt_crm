"""M12: controlled legacy-data import staging."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

BATCH_STATUSES = ("pending_review", "imported", "discarded")
ROW_STATUSES = ("ready", "error", "duplicate", "imported", "rejected", "skipped")


class ImportBatch(Base, UUIDPKMixin):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(f"status IN {BATCH_STATUSES!r}", name="status_valid"),
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(40), nullable=False, server_default="organizations")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending_review")
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ready_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column()
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="batch", lazy="selectin", order_by="ImportRow.row_number",
        cascade="all, delete-orphan",
    )


class ImportRow(Base, UUIDPKMixin):
    __tablename__ = "import_rows"
    __table_args__ = (
        CheckConstraint(f"status IN {ROW_STATUSES!r}", name="status_valid"),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    normalized: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    validation_errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    classification: Mapped[str] = mapped_column(String(20), nullable=False, server_default="prospect")
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="ready")
    imported_organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reject_reason: Mapped[str | None] = mapped_column(String(300))

    batch: Mapped[ImportBatch] = relationship(back_populates="rows")
