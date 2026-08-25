"""M3 tables: categories, brands, UOMs, products, variants.

Organization-specific pricing lives in ``app/models/organization.py`` (M2)
because it references ``crm.organizations``.
"""
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditedMixin, Base, TimestampMixin, UUIDPKMixin


class ProductCategory(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "product_categories"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    # Defines the allowed variant specification keys for this category:
    # {"attributes": [{"key","label","type","required","options","unit","min","max"}]}
    attribute_schema: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{\"attributes\": []}'::jsonb")
    )


class Brand(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    country_of_origin: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class UnitOfMeasure(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "units_of_measure"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))  # count, weight, length, volume
    decimal_scale: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class Product(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "lot_tracking_mode IN ('none','lot','lot_expiry')", name="lot_tracking_mode_valid"
        ),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="tax_rate_range"),
    )

    sku: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="RESTRICT")
    )
    base_uom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default=text("0"))
    lot_tracking_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    category: Mapped[ProductCategory] = relationship(lazy="joined")
    brand: Mapped[Brand | None] = relationship(lazy="joined")
    base_uom: Mapped[UnitOfMeasure] = relationship(lazy="joined")
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product", lazy="selectin", order_by="ProductVariant.variant_name"
    )


class ProductVariant(Base, UUIDPKMixin, AuditedMixin):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("product_id", "variant_name", name="uq_variant_product_name"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    variant_code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    variant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    uom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    # Validated against the category attribute_schema on every write.
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    product: Mapped[Product] = relationship(back_populates="variants", lazy="joined")
    uom: Mapped[UnitOfMeasure] = relationship(lazy="joined")
