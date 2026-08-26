"""M12 import pipeline: parse → normalize → validate → duplicates → approve.

Never imports directly from spreadsheet cells into production tables: every
row is staged, validated, duplicate-checked, and only an Admin approval runs
the transactional import. Organizations default to Prospect; a row becomes a
Customer only when `customer_since` explicitly confirms it. Names are never
auto-merged.
"""
import csv
import hashlib
import io
import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.models.imports import ImportBatch, ImportRow
from app.models.organization import (
    ORG_TYPES,
    CustomerProfile,
    Organization,
    OrganizationContact,
    ProspectProfile,
)
from app.services.audit import write_audit
from app.services.numbering import allocate_number
from app.services.phone import normalize_phone
from app.services.prospects import find_duplicates

EXPECTED_COLUMNS = {
    "name", "org_type", "city", "area", "source", "phone",
    "contact_name", "contact_phone", "customer_since", "payment_terms_days", "notes",
}
REQUIRED_COLUMNS = {"name"}


def _normalize_row(raw: dict) -> tuple[dict, list[str], str]:
    errors: list[str] = []
    normalized: dict = {}

    name = (raw.get("name") or "").strip()
    if len(name) < 2:
        errors.append("name is required (min 2 characters)")
    normalized["name"] = name

    org_type = (raw.get("org_type") or "other").strip().lower()
    if org_type not in ORG_TYPES:
        errors.append(f"org_type '{org_type}' invalid; allowed: {', '.join(ORG_TYPES)}")
    normalized["org_type"] = org_type

    for field in ("city", "area", "source", "contact_name", "notes"):
        value = (raw.get(field) or "").strip()
        normalized[field] = value or None

    phone = (raw.get("phone") or "").strip() or None
    normalized["phone"] = phone  # source value retained
    normalized["phone_normalized"] = normalize_phone(phone)
    contact_phone = (raw.get("contact_phone") or "").strip() or None
    normalized["contact_phone"] = contact_phone

    classification = "prospect"
    customer_since = (raw.get("customer_since") or "").strip()
    if customer_since:
        try:
            normalized["customer_since"] = date.fromisoformat(customer_since).isoformat()
            classification = "customer"
        except ValueError:
            errors.append("customer_since must be YYYY-MM-DD (leave blank for prospects)")

    terms = (raw.get("payment_terms_days") or "").strip()
    if terms:
        try:
            value = int(terms)
            if not (0 <= value <= 365):
                raise ValueError
            normalized["payment_terms_days"] = value
        except ValueError:
            errors.append("payment_terms_days must be an integer 0-365")

    return normalized, errors, classification


async def stage_import(
    session: AsyncSession, *, filename: str, content: bytes, uploaded_by: str,
) -> ImportBatch:
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailedError("The file must be UTF-8 CSV.") from exc

    reader = csv.DictReader(io.StringIO(text_content))
    if not reader.fieldnames:
        raise ValidationFailedError("The CSV has no header row.")
    headers = {h.strip().lower() for h in reader.fieldnames if h}
    unknown = headers - EXPECTED_COLUMNS
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise ValidationFailedError(
            f"Missing required column(s): {', '.join(sorted(missing))}.",
            field_errors={"file": [f"Expected columns: {', '.join(sorted(EXPECTED_COLUMNS))}"]},
        )
    if unknown:
        raise ValidationFailedError(
            f"Unknown column(s): {', '.join(sorted(unknown))}. "
            "Ambiguous data is blocked — fix the header, do not guess.",
        )

    batch = ImportBatch(
        filename=filename,
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by=uuid.UUID(uploaded_by),
    )
    session.add(batch)
    await session.flush()

    source = ready = error = duplicate = 0
    for row_number, raw in enumerate(reader, start=2):  # 1 = header
        raw = { (k or "").strip().lower(): (v or "") for k, v in raw.items() }
        if not any(v.strip() for v in raw.values()):
            continue
        source += 1
        normalized, errors, classification = _normalize_row(raw)

        duplicate_of = None
        status = "ready"
        if errors:
            status = "error"
            error += 1
        else:
            matches = await find_duplicates(
                session, name=normalized["name"],
                phone_normalized=normalized.get("phone_normalized"),
            )
            if matches:
                status = "duplicate"
                duplicate_of = uuid.UUID(matches[0]["organization_id"])
                duplicate += 1
            else:
                ready += 1

        session.add(ImportRow(
            batch_id=batch.id,
            row_number=row_number,
            raw=raw,
            normalized=normalized,
            validation_errors=errors,
            duplicate_of=duplicate_of,
            classification=classification,
            status=status,
        ))

    batch.source_count = source
    batch.ready_count = ready
    batch.error_count = error
    batch.duplicate_count = duplicate
    await session.flush()
    await write_audit(session, action="import.staged", entity_type="import_batch",
                      entity_id=batch.id,
                      new={"filename": filename, "source": source, "ready": ready,
                           "errors": error, "duplicates": duplicate})
    return batch


async def approve_import(
    session: AsyncSession, *, batch_id: uuid.UUID, user_id: str,
    include_duplicates: bool = False,
) -> ImportBatch:
    """Transactional import of ready rows. ready = imported + rejected."""
    batch = await session.get(ImportBatch, batch_id, with_for_update=True)
    if batch is None:
        raise ValidationFailedError("Import batch not found.")
    if batch.status != "pending_review":
        raise ConflictError("This batch has already been processed.", code="BATCH_PROCESSED")
    await session.refresh(batch, ["rows"])

    imported = rejected = 0
    for row in batch.rows:
        if row.status == "duplicate" and include_duplicates:
            row.status = "ready"  # Admin explicitly confirmed these are distinct
        if row.status != "ready":
            if row.status == "duplicate":
                row.status = "skipped"
            continue
        normalized = row.normalized
        try:
            org = Organization(
                org_code=await allocate_number(session, "ORG"),
                name=normalized["name"],
                org_type=normalized["org_type"],
                city=normalized.get("city"),
                area=normalized.get("area"),
                source=normalized.get("source") or f"import:{batch.filename}",
                phone=normalized.get("phone"),
                phone_normalized=normalized.get("phone_normalized"),
                notes=normalized.get("notes"),
                lifecycle_status="customer" if row.classification == "customer" else "prospect",
                converted_at=datetime.now(UTC) if row.classification == "customer" else None,
                created_by=uuid.UUID(user_id),
            )
            session.add(org)
            await session.flush()
            session.add(ProspectProfile(
                organization_id=org.id,
                stage="won" if row.classification == "customer" else "targeted",
            ))
            if row.classification == "customer":
                session.add(CustomerProfile(
                    organization_id=org.id,
                    customer_code=await allocate_number(session, "CUST"),
                    customer_since=date.fromisoformat(normalized["customer_since"]),
                    payment_terms_days=normalized.get("payment_terms_days", 30),
                ))
            if normalized.get("contact_name"):
                session.add(OrganizationContact(
                    organization_id=org.id,
                    full_name=normalized["contact_name"],
                    phone_primary=normalized.get("contact_phone"),
                    phone_primary_normalized=normalize_phone(normalized.get("contact_phone")),
                    is_primary=True,
                ))
            row.status = "imported"
            row.imported_organization_id = org.id
            imported += 1
        except Exception as exc:  # noqa: BLE001 — each row failure is recorded
            row.status = "rejected"
            row.reject_reason = str(exc)[:300]
            rejected += 1

    batch.imported_count = imported
    batch.rejected_count = rejected
    batch.status = "imported"
    batch.approved_at = datetime.now(UTC)
    batch.approved_by = uuid.UUID(user_id)
    await session.flush()
    await write_audit(session, action="import.approved", entity_type="import_batch",
                      entity_id=batch.id,
                      new={"imported": imported, "rejected": rejected,
                           "checksum": batch.checksum_sha256})
    return batch
