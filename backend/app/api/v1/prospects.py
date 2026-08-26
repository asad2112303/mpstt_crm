"""Prospect and field-sales endpoints."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.organization import (
    Activity,
    Organization,
    OrganizationProductProfile,
    ProspectProfile,
    Sample,
    Task,
)
from app.schemas.organization import (
    ActionQueueRow,
    ActivityIn,
    ActivityOut,
    DuplicateWarning,
    OrganizationOut,
    OrganizationUpdate,
    ProductProfileIn,
    ProductProfileOut,
    ProspectCreate,
    SampleFeedbackIn,
    SampleIn,
    SampleOut,
    TaskIn,
    TaskOut,
    TaskUpdate,
)
from app.services.audit import write_audit
from app.services.numbering import allocate_number
from app.services.phone import normalize_phone
from app.services.prospects import (
    advance_stage,
    find_duplicates,
    touch_activity,
    validate_manual_stage_change,
)

router = APIRouter(prefix="/prospects", tags=["prospects"])


async def _get_org(db: AsyncSession, organization_id: uuid.UUID, *, for_update: bool = False) -> Organization:
    stmt = (
        select(Organization)
        .options(
            selectinload(Organization.prospect_profile),
            selectinload(Organization.customer_profile),
        )
        .where(Organization.id == organization_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Organization)
    org = (await db.execute(stmt)).scalar_one_or_none()
    if org is None:
        raise NotFoundError("Organization not found.")
    return org


def _org_out(org: Organization) -> dict:
    return OrganizationOut.model_validate(org).model_dump(mode="json")


# ---------- list / create ----------

@router.get("")
async def list_prospects(
    params: ListParams = Depends(list_params),
    stage: str | None = Query(None),
    assigned_user_id: uuid.UUID | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(Organization)
        .join(ProspectProfile, ProspectProfile.organization_id == Organization.id)
        .options(
            selectinload(Organization.prospect_profile),
            selectinload(Organization.customer_profile),
        )
        .where(Organization.lifecycle_status == "prospect", Organization.is_active.is_(True))
    )
    if stage:
        stmt = stmt.where(ProspectProfile.stage == stage)
    if assigned_user_id:
        stmt = stmt.where(ProspectProfile.assigned_user_id == assigned_user_id)
    if params.search:
        needle = f"%{params.search.strip()}%"
        stmt = stmt.where(
            or_(
                Organization.name.ilike(needle),
                Organization.org_code.ilike(needle),
                Organization.city.ilike(needle),
                Organization.phone_normalized == normalize_phone(params.search),
            )
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Organization.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok([_org_out(o) for o in rows], page=params.page, page_size=params.page_size, total=total)


@router.post("", status_code=201)
async def create_prospect(
    payload: ProspectCreate,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    phone_norm = normalize_phone(payload.phone)
    duplicates = await find_duplicates(db, name=payload.name, phone_normalized=phone_norm)
    if duplicates and not payload.confirm_duplicate:
        raise ConflictError(
            "Similar organizations already exist. Review them, then retry with "
            "confirm_duplicate=true to create anyway. Records are never auto-merged.",
            code="DUPLICATE_SUSPECTED",
            field_errors={
                "duplicates": [DuplicateWarning(**d).model_dump_json() for d in duplicates]
            },
        )

    org_code = await allocate_number(db, "ORG")
    org = Organization(
        org_code=org_code,
        name=payload.name.strip(),
        org_type=payload.org_type,
        city=payload.city,
        area=payload.area,
        source=payload.source,
        phone=payload.phone,
        phone_normalized=phone_norm,
        notes=payload.notes,
        created_by=uuid.UUID(user.id),
    )
    db.add(org)
    await db.flush()
    db.add(
        ProspectProfile(
            organization_id=org.id,
            assigned_user_id=payload.assigned_user_id or uuid.UUID(user.id),
        )
    )
    if payload.contact_name:
        from app.models.organization import OrganizationContact

        db.add(
            OrganizationContact(
                organization_id=org.id,
                full_name=payload.contact_name,
                phone_primary=payload.phone,
                phone_primary_normalized=phone_norm,
                is_primary=True,
            )
        )
    await write_audit(db, action="prospect.created", entity_type="organization",
                      entity_id=org.id, new={"org_code": org_code, "name": org.name})
    await db.commit()
    org = await _get_org(db, org.id)
    return ok(_org_out(org))


# ---------- action queue (must precede /{organization_id}) ----------

@router.get("/action-queue")
async def action_queue(
    missing_next_action: bool | None = Query(None),
    overdue_only: bool = Query(False),
    assigned_user_id: uuid.UUID | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conditions, params = [], {}
    if missing_next_action is not None:
        conditions.append(f"missing_next_action = {'true' if missing_next_action else 'false'}")
    if overdue_only:
        conditions.append("overdue")
    if assigned_user_id:
        conditions.append("assigned_user_id = :assigned")
        params["assigned"] = str(assigned_user_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = (
        await db.execute(
            text(
                "SELECT * FROM crm.v_prospect_action_queue "
                f"{where} ORDER BY overdue DESC, next_task_due_at NULLS LAST LIMIT 200"
            ),
            params,
        )
    ).mappings().all()
    return ok([ActionQueueRow(**dict(r)).model_dump(mode="json") for r in rows])


# ---------- detail / update ----------

@router.get("/{organization_id}")
async def get_prospect(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_org(db, organization_id)
    return ok(_org_out(org))


@router.patch("/{organization_id}")
async def update_prospect(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_org(db, organization_id, for_update=True)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailedError("Nothing to update.")

    profile = org.prospect_profile
    profile_fields = {
        "stage", "assigned_user_id", "next_action_summary",
        "lost_reason", "deferred_reason", "reactivation_date",
    }
    org_changes = {k: v for k, v in changes.items() if k not in profile_fields}
    profile_changes = {k: v for k, v in changes.items() if k in profile_fields}

    if profile_changes and profile is None:
        raise ConflictError("This organization has no prospect profile.")

    if "stage" in profile_changes:
        validate_manual_stage_change(profile, profile_changes["stage"], profile_changes)

    old = {k: str(getattr(org, k, None)) for k in org_changes}
    for field, value in org_changes.items():
        setattr(org, field, value)
    if "phone" in org_changes:
        org.phone_normalized = normalize_phone(org.phone)
    org.updated_by = uuid.UUID(user.id)

    if profile is not None:
        for field, value in profile_changes.items():
            setattr(profile, field, value)

    await db.flush()
    await write_audit(db, action="prospect.updated", entity_type="organization",
                      entity_id=org.id, old=old, new={k: str(v) for k, v in changes.items()})
    await db.commit()
    org = await _get_org(db, organization_id)
    return ok(_org_out(org))


# ---------- activities ----------

@router.get("/{organization_id}/activities")
async def list_activities(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_org(db, organization_id)
    rows = (
        (
            await db.execute(
                select(Activity)
                .where(Activity.organization_id == organization_id)
                .order_by(Activity.happened_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return ok([ActivityOut.model_validate(a).model_dump(mode="json") for a in rows])


@router.post("/{organization_id}/activities", status_code=201)
async def create_activity(
    organization_id: uuid.UUID,
    payload: ActivityIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_org(db, organization_id, for_update=True)
    happened_at = payload.happened_at or datetime.now(UTC)
    activity = Activity(
        organization_id=org.id,
        contact_id=payload.contact_id,
        activity_type=payload.activity_type,
        happened_at=happened_at,
        outcome=payload.outcome,
        notes=payload.notes,
        products_discussed=payload.products_discussed,
        created_by=uuid.UUID(user.id),
    )
    db.add(activity)

    if org.prospect_profile is not None:
        touch_activity(org.prospect_profile, happened_at)
        if payload.activity_type in ("visit", "meeting"):
            advance_stage(org.prospect_profile, "visited")
        if payload.next_action_title:
            org.prospect_profile.next_action_summary = payload.next_action_title

    if payload.next_action_title:
        if payload.next_action_due_at is None:
            raise ValidationFailedError(
                "next_action_due_at is required when creating a follow-up.",
                field_errors={"next_action_due_at": ["Required"]},
            )
        db.add(
            Task(
                organization_id=org.id,
                assigned_user_id=uuid.UUID(user.id),
                title=payload.next_action_title,
                due_at=payload.next_action_due_at,
                created_by=uuid.UUID(user.id),
            )
        )

    await db.flush()
    await write_audit(db, action="activity.recorded", entity_type="organization",
                      entity_id=org.id, new={"type": payload.activity_type})
    await db.commit()
    return ok(ActivityOut.model_validate(activity).model_dump(mode="json"))


# ---------- tasks ----------

@router.get("/{organization_id}/tasks")
async def list_tasks(
    organization_id: uuid.UUID,
    status: str | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_org(db, organization_id)
    stmt = select(Task).where(Task.organization_id == organization_id)
    if status:
        stmt = stmt.where(Task.status == status)
    rows = (await db.execute(stmt.order_by(Task.due_at))).scalars().all()
    return ok([TaskOut.model_validate(t).model_dump(mode="json") for t in rows])


@router.post("/{organization_id}/tasks", status_code=201)
async def create_task(
    organization_id: uuid.UUID,
    payload: TaskIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_org(db, organization_id)
    task = Task(
        organization_id=org.id,
        assigned_user_id=payload.assigned_user_id or uuid.UUID(user.id),
        task_type=payload.task_type,
        title=payload.title,
        due_at=payload.due_at,
        priority=payload.priority,
        created_by=uuid.UUID(user.id),
    )
    db.add(task)
    if org.prospect_profile is not None:
        org.prospect_profile.next_action_summary = payload.title
    await db.flush()
    await db.commit()
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.get(Task, task_id)
    if task is None:
        raise NotFoundError("Task not found.")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailedError("Nothing to update.")
    if changes.get("status") == "done":
        task.completed_at = datetime.now(UTC)
    for field, value in changes.items():
        setattr(task, field, value)
    await db.flush()
    await db.commit()
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))


# ---------- product requirement profiles ----------

@router.get("/{organization_id}/product-profiles")
async def list_product_profiles(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_org(db, organization_id)
    rows = (
        (
            await db.execute(
                select(OrganizationProductProfile).where(
                    OrganizationProductProfile.organization_id == organization_id,
                    OrganizationProductProfile.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return ok([ProductProfileOut.model_validate(p).model_dump(mode="json") for p in rows])


@router.put("/{organization_id}/product-profiles")
async def replace_product_profiles(
    organization_id: uuid.UUID,
    payload: list[ProductProfileIn],
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_org(db, organization_id, for_update=True)
    for item in payload:
        if (item.min_quantity and item.max_quantity and item.min_quantity > item.max_quantity):
            raise ValidationFailedError(
                "Minimum quantity cannot exceed maximum quantity.",
                field_errors={"min_quantity": ["min > max"]},
            )

    existing = (
        (
            await db.execute(
                select(OrganizationProductProfile).where(
                    OrganizationProductProfile.organization_id == organization_id
                )
            )
        )
        .scalars()
        .all()
    )
    for row in existing:
        row.is_active = False
    for item in payload:
        db.add(
            OrganizationProductProfile(
                organization_id=organization_id, **item.model_dump(), is_active=True
            )
        )
    if payload and org.prospect_profile is not None:
        advance_stage(org.prospect_profile, "requirement_collected")

    await db.flush()
    await write_audit(db, action="product_profiles.replaced", entity_type="organization",
                      entity_id=organization_id, new={"count": len(payload)})
    await db.commit()
    return await list_product_profiles(organization_id, user, db)


# ---------- samples ----------

@router.get("/{organization_id}/samples")
async def list_samples(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_org(db, organization_id)
    rows = (
        (
            await db.execute(
                select(Sample)
                .where(Sample.organization_id == organization_id)
                .order_by(Sample.issued_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return ok([SampleOut.model_validate(s).model_dump(mode="json") for s in rows])


@router.post("/{organization_id}/samples", status_code=201)
async def create_sample(
    organization_id: uuid.UUID,
    payload: SampleIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_org(db, organization_id, for_update=True)
    sample = Sample(
        organization_id=org.id,
        product_id=payload.product_id,
        product_variant_id=payload.product_variant_id,
        quantity=payload.quantity,
        uom_id=payload.uom_id,
        issued_at=payload.issued_at or datetime.now(UTC),
        receiver_name=payload.receiver_name,
        feedback_due_date=payload.feedback_due_date,
        created_by=uuid.UUID(user.id),
    )
    db.add(sample)
    if org.prospect_profile is not None:
        advance_stage(org.prospect_profile, "sample_provided")
        touch_activity(org.prospect_profile, sample.issued_at)
    await db.flush()
    await write_audit(db, action="sample.issued", entity_type="sample", entity_id=sample.id,
                      new={"organization_id": str(org.id), "quantity": str(payload.quantity)})
    await db.commit()
    return ok(SampleOut.model_validate(sample).model_dump(mode="json"))


@router.patch("/samples/{sample_id}/feedback")
async def sample_feedback(
    sample_id: uuid.UUID,
    payload: SampleFeedbackIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sample = await db.get(Sample, sample_id)
    if sample is None:
        raise NotFoundError("Sample not found.")
    old_status = sample.status
    sample.status = payload.status
    if payload.feedback is not None:
        sample.feedback = payload.feedback
    await db.flush()
    await write_audit(db, action="sample.feedback", entity_type="sample", entity_id=sample.id,
                      old={"status": old_status}, new={"status": payload.status})
    await db.commit()
    return ok(SampleOut.model_validate(sample).model_dump(mode="json"))
