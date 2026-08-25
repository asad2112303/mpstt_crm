"""Standard success envelope helpers."""
from typing import Any

from app.core.context import request_id_var


def ok(data: Any, *, page: int | None = None, page_size: int | None = None, total: int | None = None) -> dict:
    meta: dict[str, Any] = {"request_id": request_id_var.get()}
    if page is not None:
        meta["page"] = page
    if page_size is not None:
        meta["page_size"] = page_size
    if total is not None:
        meta["total"] = total
    return {"data": data, "meta": meta}
