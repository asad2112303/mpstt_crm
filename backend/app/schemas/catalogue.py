"""Pydantic schemas for the catalogue module."""
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    attribute_schema: dict = Field(default_factory=lambda: {"attributes": []})
    is_active: bool = True


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    attribute_schema: dict
    is_active: bool


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=200)
    country_of_origin: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    manufacturer: str | None
    country_of_origin: str | None
    is_active: bool


class UomIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=80)
    category: str | None = Field(default=None, max_length=50)
    decimal_scale: int = Field(default=0, ge=0, le=3)
    is_active: bool = True


class UomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    category: str | None
    decimal_scale: int
    is_active: bool


class VariantIn(BaseModel):
    variant_code: str = Field(min_length=1, max_length=60)
    variant_name: str = Field(min_length=1, max_length=200)
    uom_id: uuid.UUID | None = None  # defaults to product base UOM
    attributes: dict = Field(default_factory=dict)
    is_active: bool = True


class VariantUpdate(BaseModel):
    variant_name: str | None = Field(default=None, min_length=1, max_length=200)
    uom_id: uuid.UUID | None = None
    attributes: dict | None = None
    is_active: bool | None = None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    variant_code: str
    variant_name: str
    uom_id: uuid.UUID
    attributes: dict
    is_active: bool


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=2, max_length=200)
    category_id: uuid.UUID
    brand_id: uuid.UUID | None = None
    base_uom_id: uuid.UUID
    description: str | None = None
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    lot_tracking_mode: str = Field(default="none", pattern="^(none|lot|lot_expiry)$")
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    brand_id: uuid.UUID | None = None
    description: str | None = None
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    lot_tracking_mode: str | None = Field(default=None, pattern="^(none|lot|lot_expiry)$")
    is_active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sku: str
    name: str
    category_id: uuid.UUID
    brand_id: uuid.UUID | None
    base_uom_id: uuid.UUID
    description: str | None
    tax_rate: Decimal
    lot_tracking_mode: str
    is_active: bool
    variants: list[VariantOut] = []


class ProductListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sku: str
    name: str
    is_active: bool
    tax_rate: Decimal
    category_name: str
    brand_name: str | None
    base_uom_code: str
    variant_count: int


class SearchHit(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    label: str
    sku: str
    variant_code: str | None
    uom_code: str
