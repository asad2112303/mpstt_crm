"""Private file storage.

Two backends behind one interface:
- ``SupabaseStorage``: private Supabase Storage buckets via the Storage REST
  API using the service-role key (server-side only). Downloads use short-lived
  signed URLs. Mandatory in staging/production.
- ``LocalStorage``: filesystem under LOCAL_STORAGE_DIR for dev/tests.

Upload validation lives here: MIME/extension allowlist, size cap, magic-byte
sniffing, sanitized names, and traversal rejection. The browser MIME type is
never trusted.
"""
import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import Settings
from app.core.errors import AppError, ValidationFailedError

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# extension -> (mime allowlist, magic prefixes)
ALLOWED_TYPES: dict[str, tuple[set[str], list[bytes]]] = {
    ".pdf": ({"application/pdf"}, [b"%PDF-"]),
    ".png": ({"image/png"}, [b"\x89PNG\r\n\x1a\n"]),
    ".jpg": ({"image/jpeg"}, [b"\xff\xd8\xff"]),
    ".jpeg": ({"image/jpeg"}, [b"\xff\xd8\xff"]),
    ".webp": ({"image/webp"}, [b"RIFF"]),
    ".xlsx": (
        {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        [b"PK\x03\x04"],
    ),
    ".csv": ({"text/csv", "application/vnd.ms-excel", "text/plain"}, []),
}


class StorageError(AppError):
    status_code = 502
    code = "STORAGE_ERROR"


def sanitize_filename(name: str) -> str:
    base = Path(name).name  # strips any path components
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base[:120] or "file"


def validate_upload(filename: str, content: bytes, claimed_mime: str) -> tuple[str, str, str]:
    """Returns (sanitized_name, extension, verified_mime) or raises 422."""
    if len(content) == 0:
        raise ValidationFailedError("The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValidationFailedError(
            f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
        )
    sanitized = sanitize_filename(filename)
    ext = Path(sanitized).suffix.lower()
    if ext not in ALLOWED_TYPES:
        raise ValidationFailedError(
            "This file type is not allowed. Allowed: PDF, PNG, JPG, WEBP, XLSX, CSV.",
            field_errors={"file": [f"Extension {ext or '(none)'} not allowed"]},
        )
    mimes, magics = ALLOWED_TYPES[ext]
    if magics and not any(content.startswith(m) for m in magics):
        raise ValidationFailedError(
            "The file content does not match its extension.",
            field_errors={"file": ["Magic-byte check failed"]},
        )
    verified_mime = claimed_mime if claimed_mime in mimes else next(iter(mimes))
    return sanitized, ext, verified_mime


def make_storage_path(entity_type: str, entity_id: str, sanitized_name: str) -> str:
    if not re.fullmatch(r"[a-z_]{2,40}", entity_type):
        raise ValidationFailedError("Invalid entity type.")
    return f"{entity_type}/{entity_id}/{uuid.uuid4()}-{sanitized_name}"


def checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass
class StoredFile:
    bucket: str
    path: str


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)

    def _full(self, bucket: str, path: str) -> Path:
        full = (self.root / bucket / path).resolve()
        if not str(full).startswith(str(self.root.resolve())):
            raise ValidationFailedError("Invalid storage path.")
        return full

    async def put(self, bucket: str, path: str, content: bytes, mime: str) -> StoredFile:
        full = self._full(bucket, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content)
        return StoredFile(bucket=bucket, path=path)

    async def get(self, bucket: str, path: str) -> bytes:
        full = self._full(bucket, path)
        if not full.is_file():
            raise StorageError("Stored file is missing.")
        return full.read_bytes()

    async def signed_url(self, bucket: str, path: str, expires_seconds: int = 300) -> None:
        return None  # local backend streams instead


class SupabaseStorage:
    def __init__(self, settings: Settings):
        self.base = settings.supabase_url.rstrip("/")
        self.key = settings.supabase_service_role_key

    def _headers(self) -> dict:
        return {"apikey": self.key, "Authorization": f"Bearer {self.key}"}

    async def put(self, bucket: str, path: str, content: bytes, mime: str) -> StoredFile:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base}/storage/v1/object/{bucket}/{path}",
                headers={**self._headers(), "Content-Type": mime, "x-upsert": "false"},
                content=content,
            )
        if resp.status_code >= 400:
            raise StorageError("Upload to storage failed.")
        return StoredFile(bucket=bucket, path=path)

    async def get(self, bucket: str, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base}/storage/v1/object/{bucket}/{path}", headers=self._headers()
            )
        if resp.status_code >= 400:
            raise StorageError("Download from storage failed.")
        return resp.content

    async def signed_url(self, bucket: str, path: str, expires_seconds: int = 300) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}/storage/v1/object/sign/{bucket}/{path}",
                headers=self._headers(),
                json={"expiresIn": expires_seconds},
            )
        if resp.status_code >= 400:
            raise StorageError("Could not create a signed URL.")
        return f"{self.base}/storage/v1{resp.json()['signedURL']}"


def get_storage(settings: Settings):
    if settings.storage_backend == "supabase":
        return SupabaseStorage(settings)
    return LocalStorage(settings.local_storage_dir)
