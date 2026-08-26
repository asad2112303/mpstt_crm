"""M12: Admin-only import endpoints."""
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import NotFoundError
from app.core.security import CurrentUser, require_admin
from app.models.imports import ImportBatch
from app.services.imports import approve_import, stage_import

router = APIRouter(prefix="/admin/imports", tags=["imports"])


def batch_out(batch: ImportBatch, *, with_rows: bool = False) -> dict:
    data = {
        "id": str(batch.id),
        "filename": batch.filename,
        "status": batch.status,
        "source_count": batch.source_count,
        "ready_count": batch.ready_count,
        "error_count": batch.error_count,
        "duplicate_count": batch.duplicate_count,
        "imported_count": batch.imported_count,
        "rejected_count": batch.rejected_count,
        "checksum_sha256": batch.checksum_sha256,
        "created_at": batch.created_at.isoformat(),
        "approved_at": batch.approved_at.isoformat() if batch.approved_at else None,
    }
    if with_rows:
        data["rows"] = [
            {
                "id": str(r.id),
                "row_number": r.row_number,
                "normalized": r.normalized,
                "validation_errors": r.validation_errors,
                "duplicate_of": str(r.duplicate_of) if r.duplicate_of else None,
                "classification": r.classification,
                "status": r.status,
                "reject_reason": r.reject_reason,
                "imported_organization_id":
                    str(r.imported_organization_id) if r.imported_organization_id else None,
            }
            for r in batch.rows
        ]
    return data


@router.get("")
async def list_batches(
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        (await db.execute(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50)))
        .scalars().all()
    )
    return ok([batch_out(b) for b in rows])


@router.post("", status_code=201)
async def upload_batch(
    file: UploadFile = File(...),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content = await file.read()
    batch = await stage_import(
        db, filename=file.filename or "import.csv", content=content, uploaded_by=admin.id
    )
    await db.commit()
    loaded = (
        await db.execute(
            select(ImportBatch)
            .options(selectinload(ImportBatch.rows))
            .where(ImportBatch.id == batch.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return ok(batch_out(loaded, with_rows=True))


@router.get("/{batch_id}")
async def get_batch(
    batch_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    batch = (
        await db.execute(
            select(ImportBatch)
            .options(selectinload(ImportBatch.rows))
            .where(ImportBatch.id == batch_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if batch is None:
        raise NotFoundError("Import batch not found.")
    return ok(batch_out(batch, with_rows=True))


@router.post("/{batch_id}/approve")
async def approve_batch(
    batch_id: uuid.UUID,
    payload: dict | None = None,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    include_duplicates = bool((payload or {}).get("include_duplicates", False))
    batch = await approve_import(
        db, batch_id=batch_id, user_id=admin.id, include_duplicates=include_duplicates
    )
    await db.commit()
    return ok(batch_out(batch, with_rows=True))
