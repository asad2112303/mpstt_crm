"""Pydantic schemas for organizations, prospects, and field sales."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.organization import ACTIVITY_TYPES, ORG_TYPES

ORG_TYPE_PATTERN = f"^({'|'.join(ORG_TYPES)})$"
ACTIVITY_PATTERN = f"^({'|'.join(ACTIVITY_TYPES)})$"


# ---------- organizations / prospects ----------

class ProspectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    org_type: str = Field(pattern=ORG_TYPE_PATTERN)
    city: str | None = Field(default=None, max_length=100)
    area: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    contact_name: str | None = Field(default=None, max_length=150)
    notes: str | None = None
    assigned_user_id: uuid.UUID | None = None
    # Set true to create anyway after reviewing duplicate warnings.
    confirm_duplicate: bool = False


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    org_type: str | None = Field(default=None, pattern=ORG_TYPE_PATTERN)
    city: str | None = Field(default=None, max_length=100)
    area: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    ntn: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    is_active: bool | None = None
    # Prospect-profile fields:
    stage: str | None = None
    assigned_user_id: uuid.UUID | None = None
    next_action_summary: str | None = Field(default=None, max_length=300)
    lost_reason: str | None = None
    deferred_reason: str | None = None
    reactivation_date: date | None = None


class ProspectProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stage: str
    assigned_user_id: uuid.UUID | None
    first_contact_date: date | None
    last_activity_at: datetime | None
    next_action_summary: str | None
    lost_reason: str | None
    deferred_reason: str | None
    reactivation_date: date | None


class CustomerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    customer_code: str
    customer_since: date
    payment_terms_days: int
    credit_limit: Decimal | None
    account_status: str
    billing_notes: str | None
    purchasing_notes: str | None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    org_code: str
    name: str
    legal_name: str | None
    org_type: str
    lifecycle_status: str
    city: str | None
    area: str | None
    source: str | None
    phone: str | None
    ntn: str | None
    notes: str | None
    is_active: bool
    converted_at: datetime | None
    created_at: datetime
    prospect_profile: ProspectProfileOut | None
    customer_profile: CustomerProfileOut | None


class DuplicateWarning(BaseModel):
    organization_id: str
    org_code: str
    name: str
    city: str | None
    lifecycle_status: str
    name_similarity: float
    same_phone: bool


# ---------- branches / contacts ----------

class BranchIn(BaseModel):
    branch_name: str = Field(min_length=1, max_length=150)
    area: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    delivery_address: str | None = None
    billing_address: str | None = None
    map_url: str | None = Field(default=None, max_length=500)
    route_cluster: str | None = Field(default=None, max_length=100)
    is_primary: bool = False
    is_active: bool = True


class BranchOut(BranchIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID


class ContactIn(BaseModel):
    branch_id: uuid.UUID | None = None
    full_name: str = Field(min_length=1, max_length=150)
    designation: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    phone_primary: str | None = Field(default=None, max_length=50)
    phone_alt: str | None = Field(default=None, max_length=50)
    whatsapp: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    preferred_channel: str | None = Field(default=None, max_length=20)
    is_primary: bool = False
    is_active: bool = True


class ContactOut(ContactIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID


# ---------- activities / tasks ----------

class ActivityIn(BaseModel):
    activity_type: str = Field(pattern=ACTIVITY_PATTERN)
    happened_at: datetime | None = None
    contact_id: uuid.UUID | None = None
    outcome: str | None = Field(default=None, max_length=300)
    notes: str | None = None
    products_discussed: str | None = None
    # Optionally create the next follow-up task in the same call.
    next_action_title: str | None = Field(default=None, max_length=300)
    next_action_due_at: datetime | None = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    contact_id: uuid.UUID | None
    activity_type: str
    happened_at: datetime
    outcome: str | None
    notes: str | None
    products_discussed: str | None
    created_by: uuid.UUID | None
    created_at: datetime


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    task_type: str = Field(default="follow_up", max_length=40)
    due_at: datetime
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    assigned_user_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    due_at: datetime | None = None
    priority: str | None = Field(default=None, pattern="^(low|normal|high)$")
    status: str | None = Field(default=None, pattern="^(open|done|cancelled)$")
    completion_outcome: str | None = None
    assigned_user_id: uuid.UUID | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID | None
    assigned_user_id: uuid.UUID | None
    task_type: str
    title: str
    due_at: datetime
    priority: str
    status: str
    completion_outcome: str | None
    completed_at: datetime | None
    created_at: datetime


# ---------- requirements / samples / prices ----------

class ProductProfileIn(BaseModel):
    product_id: uuid.UUID
    product_variant_id: uuid.UUID | None = None
    frequency: str | None = Field(default=None, pattern="^(weekly|monthly|quarterly|adhoc)$")
    min_quantity: Decimal | None = Field(default=None, gt=0)
    max_quantity: Decimal | None = Field(default=None, gt=0)
    uom_id: uuid.UUID | None = None
    current_supplier: str | None = Field(default=None, max_length=200)
    current_rate: Decimal | None = Field(default=None, gt=0)
    specification_notes: str | None = None


class ProductProfileOut(ProductProfileIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    is_active: bool
    # Resolved labels so the requirement list is readable without the client
    # having to fetch the catalogue for every row.
    product_name: str | None = None
    product_sku: str | None = None
    variant_name: str | None = None
    uom_code: str | None = None


class SampleIn(BaseModel):
    product_id: uuid.UUID
    product_variant_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0)
    uom_id: uuid.UUID | None = None
    issued_at: datetime | None = None
    receiver_name: str | None = Field(default=None, max_length=150)
    feedback_due_date: date | None = None


class SampleFeedbackIn(BaseModel):
    status: str = Field(pattern="^(feedback_received|converted|closed)$")
    feedback: str | None = None


class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    product_id: uuid.UUID
    product_variant_id: uuid.UUID | None
    quantity: Decimal
    uom_id: uuid.UUID | None
    issued_at: datetime
    receiver_name: str | None
    feedback_due_date: date | None
    status: str
    feedback: str | None
    created_at: datetime


class PriceIn(BaseModel):
    product_id: uuid.UUID
    product_variant_id: uuid.UUID | None = None
    price_type: str = Field(default="quoted", pattern="^(quoted|agreed|list)$")
    unit_price: Decimal = Field(gt=0)
    uom_id: uuid.UUID | None = None
    effective_from: date
    effective_to: date | None = None
    source_reference: str | None = Field(default=None, max_length=200)


class PriceOut(PriceIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime


class ActionQueueRow(BaseModel):
    organization_id: uuid.UUID
    org_code: str
    name: str
    city: str | None
    area: str | None
    stage: str
    assigned_user_id: uuid.UUID | None
    last_activity_at: datetime | None
    next_action_summary: str | None
    next_task_due_at: datetime | None
    open_task_count: int
    missing_next_action: bool
    overdue: bool
    days_since_last_activity: int | None
