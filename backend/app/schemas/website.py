"""Pydantic schemas for website intake (public.quotation_requests)."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QuotationRequestStatus = Literal[
    "new",
    "contacted",
    "quotation_preparing",
    "quotation_sent",
    "won",
    "lost",
    "closed",
]


class QuotationRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    full_name: str
    organization: str
    phone: str
    email: str | None
    organization_type: str | None
    requirement: str
    consent: bool
    consent_at: datetime
    source_page: str | None
    product_slug: str | None
    category_slug: str | None
    product_name: str | None
    intent: str | None
    status: str
    internal_notes: str | None
    contacted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class QuotationRequestUpdate(BaseModel):
    """The only columns the CRM may write. Everything else is the website's."""

    status: QuotationRequestStatus | None = None
    internal_notes: str | None = Field(default=None, max_length=5000)


class QuotationRequestSummary(BaseModel):
    total: int
    # status -> count, every known status present (zero when unused).
    by_status: dict[str, int]
    new_count: int
    open_count: int
