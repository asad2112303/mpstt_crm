"""M11: private document upload/download and metadata linking."""
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.documents import BUCKETS, Document
from app.services.audit import write_audit
from app.services.storage import (
    checksum,
    get_storage,
    make_storage_path,
    validate_upload,
)

router = APIRouter(prefix="/documents", tags=["documents"])

# entity_type -> default bucket
ENTITY_BUCKETS = {
    "quotation": "commercial-documents",
    "sales_order": "commercial-documents",
    "invoice": "commercial-documents",
    "receipt": "commercial-documents",
    "organization": "commercial-documents",
    "sample": "commercial-documents",
    "company": "commercial-documents",
    "delivery": "delivery-pod",
    "proof_of_delivery": "delivery-pod",
    "payment": "payment-proofs",
}


def document_out(doc: Document) -> dict:
    return {
        "id": str(doc.id),
        "organization_id": str(doc.organization_id) if doc.organization_id else None,
        "entity_type": doc.entity_type,
        "entity_id": doc.entity_id,
        "document_type": doc.document_type,
        "original_filename": doc.original_filename,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "created_at": doc.created_at.isoformat(),
    }


async def store_document(
    db: AsyncSession,
    settings: Settings,
    *,
    content: bytes,
    filename: str,
    claimed_mime: str,
    entity_type: str,
    entity_id: str,
    document_type: str,
    organization_id: uuid.UUID | None,
    uploaded_by: uuid.UUID | None,
) -> Document:
    """Shared by the upload endpoint and server-generated PDFs (M5/M7/M8/M9)."""
    if entity_type not in ENTITY_BUCKETS:
        raise ValidationFailedError(
            "Unknown entity type.", field_errors={"entity_type": ["Invalid"]}
        )
    sanitized, _ext, verified_mime = validate_upload(filename, content, claimed_mime)
    bucket = ENTITY_BUCKETS[entity_type]
    assert bucket in BUCKETS
    path = make_storage_path(entity_type, entity_id, sanitized)

    storage = get_storage(settings)
    await storage.put(bucket, path, content, verified_mime)

    doc = Document(
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        document_type=document_type,
        bucket=bucket,
        storage_path=path,
        original_filename=sanitized,
        mime_type=verified_mime,
        size_bytes=len(content),
        checksum_sha256=checksum(content),
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    await db.flush()
    return doc


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    entity_type: str = Form(...),
    entity_id: str = Form(...),
    document_type: str = Form("attachment"),
    organization_id: uuid.UUID | None = Form(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    content = await file.read()
    doc = await store_document(
        db, settings,
        content=content,
        filename=file.filename or "file",
        claimed_mime=file.content_type or "application/octet-stream",
        entity_type=entity_type,
        entity_id=entity_id,
        document_type=document_type,
        organization_id=organization_id,
        uploaded_by=uuid.UUID(user.id),
    )
    await write_audit(db, action="document.uploaded", entity_type="document",
                      entity_id=doc.id,
                      new={"for": f"{entity_type}/{entity_id}", "name": doc.original_filename})
    await db.commit()
    return ok(document_out(doc))


@router.get("")
async def list_documents(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        (
            await db.execute(
                select(Document)
                .where(Document.entity_type == entity_type, Document.entity_id == entity_id)
                .order_by(Document.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return ok([document_out(d) for d in rows])


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Document not found.")

    storage = get_storage(settings)
    signed = await storage.signed_url(doc.bucket, doc.storage_path, expires_seconds=300)
    await write_audit(db, action="document.downloaded", entity_type="document",
                      entity_id=doc.id, new={"name": doc.original_filename})
    await db.commit()
    if signed:
        return ok({"url": signed, "expires_in": 300, "filename": doc.original_filename})

    content = await storage.get(doc.bucket, doc.storage_path)
    return Response(
        content=content,
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.original_filename}"',
            "Cache-Control": "no-store",
        },
    )
