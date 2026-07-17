from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class SortParams(BaseModel):
    sort_by: str | None = Field(default=None, description="Field to sort by")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$", description="Sort order")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


async def paginate(
    session: AsyncSession,
    query: Select,
    params: PaginationParams,
) -> tuple[list[Any], int]:
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query) or 0

    offset = (params.page - 1) * params.page_size
    query = query.offset(offset).limit(params.page_size)
    result = await session.execute(query)
    items = result.scalars().all()

    return list(items), total


def create_paginated_response(
    items: list[T],
    total: int,
    params: PaginationParams,
) -> PaginatedResponse[T]:
    total_pages = (total + params.page_size - 1) // params.page_size
    return PaginatedResponse(
        items=items,
        total=total,
        page=params.page,
        page_size=params.page_size,
        total_pages=total_pages,
    )


def apply_sorting(query: Select, model: Any, params: SortParams) -> Select:
    if params.sort_by and hasattr(model, params.sort_by):
        column = getattr(model, params.sort_by)
        if params.sort_order == "desc":
            query = query.order_by(column.desc())
        else:
            query = query.order_by(column.asc())
    return query