from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.common.models import Note, Notification, Reminder, Ticket, User
from src.common.pagination import apply_sorting, paginate, create_paginated_response
from src.tickets.schemas import TicketSearchParams


class TicketRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, ticket: Ticket) -> Ticket:
        self.session.add(ticket)
        await self.session.flush()
        await self.session.refresh(ticket)
        return ticket

    async def get_by_id(self, ticket_id: int) -> Optional[Ticket]:
        result = await self.session.execute(
            select(Ticket)
            .options(selectinload(Ticket.assignee))
            .where(Ticket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def search(
        self, params: TicketSearchParams, user: User
    ) -> tuple[list[Ticket], int]:
        query = select(Ticket).options(selectinload(Ticket.assignee))

        if user.role.value == "AGENT":
            query = query.where(
                (Ticket.assignee_id == user.id) | (Ticket.assignee_id.is_(None))
            )

        if params.status:
            query = query.where(Ticket.status == params.status)
        if params.priority:
            query = query.where(Ticket.priority == params.priority)
        if params.category:
            query = query.where(Ticket.category == params.category)
        if params.assignee_id:
            query = query.where(Ticket.assignee_id == params.assignee_id)

        # Full-text search on Postgres (generated tsvector column + GIN
        # index, see migration a3f7c9e21d40). SQLite has no FTS engine
        # wired up here, so the test suite (see tests/conftest.py) falls
        # back to a plain ILIKE match - correct results, just an
        # unindexed scan, which is fine at test-database scale. See
        # DECISIONS.md "Ticket search & filtering" for the tradeoffs.
        rank_expr = None
        if params.keyword:
            dialect_name = self.session.bind.dialect.name if self.session.bind else "postgresql"
            if dialect_name == "postgresql":
                tsquery = func.websearch_to_tsquery("english", params.keyword)
                query = query.where(Ticket.search_vector.op("@@")(tsquery))
                rank_expr = func.ts_rank(Ticket.search_vector, tsquery)
            else:
                like = f"%{params.keyword}%"
                query = query.where(
                    Ticket.title.ilike(like) | Ticket.description.ilike(like)
                )

        if params.created_after:
            query = query.where(Ticket.created_at >= params.created_after)
        if params.created_before:
            query = query.where(Ticket.created_at <= params.created_before)

        if rank_expr is not None:
            # Most-relevant match first, most-recent as tiebreaker.
            query = query.order_by(rank_expr.desc(), Ticket.created_at.desc())
        else:
            query = query.order_by(Ticket.created_at.desc())

        pagination_params = type(
            "PaginationParams", (), {"page": params.page, "page_size": params.page_size}
        )()

        return await paginate(self.session, query, pagination_params)

    async def update(self, ticket: Ticket, **kwargs) -> Ticket:
        for key, value in kwargs.items():
            if hasattr(ticket, key) and value is not None:
                setattr(ticket, key, value)
        await self.session.flush()
        await self.session.refresh(ticket)
        return ticket

    async def delete(self, ticket: Ticket) -> None:
        await self.session.delete(ticket)


class NoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, note: Note) -> Note:
        self.session.add(note)
        await self.session.flush()
        await self.session.refresh(note)
        return note

    async def get_by_ticket(
        self, ticket_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[Note], int]:
        query = select(Note).where(Note.ticket_id == ticket_id).order_by(Note.created_at.desc())
        pagination_params = type(
            "PaginationParams", (), {"page": page, "page_size": page_size}
        )()
        return await paginate(self.session, query, pagination_params)


class ReminderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, reminder: Reminder) -> Reminder:
        self.session.add(reminder)
        await self.session.flush()
        await self.session.refresh(reminder)
        return reminder

    async def get_by_ticket(self, ticket_id: int) -> list[Reminder]:
        result = await self.session.execute(
            select(Reminder).where(Reminder.ticket_id == ticket_id)
        )
        return list(result.scalars().all())

    async def get_pending(self) -> list[Reminder]:
        result = await self.session.execute(
            select(Reminder)
            .where(
                Reminder.status == "PENDING",
                Reminder.scheduled_time <= datetime.utcnow(),
            )
            .options(selectinload(Reminder.ticket).selectinload(Ticket.assignee))
        )
        return list(result.scalars().all())

    async def update_status(self, reminder: Reminder, status: str) -> Reminder:
        reminder.status = status
        await self.session.flush()
        await self.session.refresh(reminder)
        return reminder


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.flush()
        await self.session.refresh(notification)
        return notification