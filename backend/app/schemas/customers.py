"""Schemas for customers, conversion, and orders."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemIn(BaseModel):
    product_variant_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class ConvertIn(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1)
    branch_id: uuid.UUID | None = None
    customer_po_number: str | None = Field(default=None, max_length=100)
    is_direct_po: bool = True
    source_quotation_id: uuid.UUID | None = None
    expected_delivery_date: date | None = None
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    credit_limit: Decimal | None = Field(default=None, ge=0)
    order_notes: str | None = None


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    product_variant_id: uuid.UUID
    description_snapshot: str
    specification_snapshot: dict
    quantity: Decimal
    uom_code: str
    unit_price: Decimal
    discount_percent: Decimal
    tax_rate: Decimal
    line_net: Decimal
    line_tax: Decimal
    line_total: Decimal
    sort_order: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_number: str
    organization_id: uuid.UUID
    branch_id: uuid.UUID | None
    source_quotation_id: uuid.UUID | None
    is_direct_po: bool
    customer_po_number: str | None
    order_date: date
    expected_delivery_date: date | None
    status: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    notes: str | None
    cancelled_reason: str | None
    created_at: datetime
    items: list[OrderItemOut] = []


class CustomerUpdate(BaseModel):
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    credit_limit: Decimal | None = Field(default=None, ge=0)
    billing_notes: str | None = None
    purchasing_notes: str | None = None
    account_status: str | None = Field(default=None, pattern="^(active|on_hold|closed)$")


class TimelineEvent(BaseModel):
    kind: str
    at: datetime
    title: str
    detail: str | None = None
    reference_id: str | None = None
