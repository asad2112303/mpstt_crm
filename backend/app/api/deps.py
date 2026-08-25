"""Shared API dependencies (pagination/search params)."""
from dataclasses import dataclass

from fastapi import Query

MAX_PAGE_SIZE = 100


@dataclass
class ListParams:
    page: int
    page_size: int
    search: str | None
    status: str | None
    sort: str | None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def list_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=200),
    status: str | None = Query(None, max_length=50),
    sort: str | None = Query(None, max_length=50),
) -> ListParams:
    return ListParams(page=page, page_size=page_size, search=search, status=status, sort=sort)
