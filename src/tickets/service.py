from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.common.exceptions import ForbiddenException, NotFoundException
from src.common.logging import get_logger, BackgroundTaskLogger
from src.common.models import Note, Notification, Reminder, Ticket
from src.llm.service import llm_service
from src.tickets.repository import (
    NoteRepository,
    NotificationRepository,
    ReminderRepository,
    TicketRepository,
)
from src.tickets.schemas import (
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    ReminderCreate,
    ReminderResponse,
    TicketAssign,
    TicketCreate,
    TicketListResponse,
    TicketResponse,
    TicketSearchParams,
    TicketUpdate,
)

logger = get_logger(__name__)


class TicketService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.ticket_repo = TicketRepository(session)
        self.note_repo = NoteRepository(session)
        self.reminder_repo = ReminderRepository(session)
        self.notification_repo = NotificationRepository(session)

    async def create_ticket(self, ticket_data: TicketCreate, customer: User) -> TicketResponse:
        ticket = Ticket(
            title=ticket_data.title,
            description=ticket_data.description,
            customer_email=ticket_data.customer_email,
            status="OPEN",
            priority="MEDIUM",
            category="OTHER",
        )
        ticket = await self.ticket_repo.create(ticket)

        await self.session.commit()

        # Trigger Celery task for ticket classification. This is
        # best-effort, not a hard dependency: the ticket is already
        # committed above, so a broker outage (Redis down, network blip)
        # must not turn an otherwise-successful ticket creation into a 500.
        # The ticket simply stays at classification_status=PENDING /
        # manual_triage=False until it's retried or handled manually - it
        # does not silently disappear.
        from src.tasks.classification_tasks import classify_ticket_task
        try:
            classify_ticket_task.delay(ticket.id)
        except Exception as exc:
            logger.error(
                "classification_enqueue_failed",
                ticket_id=ticket.id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        return TicketResponse.model_validate(ticket)

    async def get_ticket(self, ticket_id: int, user: User) -> TicketResponse:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")
        self._ensure_can_view(ticket, user)
        return TicketResponse.model_validate(ticket)

    @staticmethod
    def _ensure_can_view(ticket: Ticket, user: User) -> None:
        """Agents may view tickets that are unassigned or assigned to them.
        Admins may view any ticket. Enforced here (service layer) so it can
        never be bypassed by hitting /tickets/{id} directly."""
        if user.role.value == "AGENT" and ticket.assignee_id not in (None, user.id):
            raise ForbiddenException("Not authorized to view this ticket")

    @staticmethod
    def _ensure_can_modify(ticket: Ticket, user: User) -> None:
        if user.role.value == "AGENT" and ticket.assignee_id != user.id:
            raise ForbiddenException("Not authorized to modify this ticket")

    async def search_tickets(
        self, params: TicketSearchParams, user: User
    ) -> TicketListResponse:
        items, total = await self.ticket_repo.search(params, user)
        total_pages = (total + params.page_size - 1) // params.page_size

        return TicketListResponse(
            items=[TicketResponse.model_validate(t) for t in items],
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
        )

    async def update_ticket(
        self, ticket_id: int, update_data: TicketUpdate, user: User
    ) -> TicketResponse:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")

        self._ensure_can_modify(ticket, user)

        update_dict = update_data.model_dump(exclude_unset=True)
        ticket = await self.ticket_repo.update(ticket, **update_dict)

        return TicketResponse.model_validate(ticket)

    async def assign_ticket(
        self, ticket_id: int, assign_data: TicketAssign, user: User
    ) -> TicketResponse:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")

        from src.auth.repository import UserRepository

        assignee = await UserRepository(self.session).get_by_id(assign_data.assignee_id)
        if not assignee:
            raise NotFoundException("Assignee not found")

        ticket.assignee_id = assign_data.assignee_id
        await self.session.flush()
        await self.session.refresh(ticket)

        return TicketResponse.model_validate(ticket)

    async def delete_ticket(self, ticket_id: int, user: User) -> None:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")

        if user.role.value != "ADMIN":
            raise ForbiddenException("Only admins can delete tickets")

        await self.ticket_repo.delete(ticket)

    async def add_note(
        self, ticket_id: int, note_data: NoteCreate, user: User
    ) -> NoteResponse:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")

        self._ensure_can_modify(ticket, user)

        note = Note(ticket_id=ticket_id, agent_id=user.id, note=note_data.note)
        note = await self.note_repo.create(note)

        return NoteResponse.model_validate(note)

    async def get_notes(
        self, ticket_id: int, user: User, page: int = 1, page_size: int = 20
    ) -> NoteListResponse:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")
        self._ensure_can_view(ticket, user)

        items, total = await self.note_repo.get_by_ticket(ticket_id, page, page_size)
        total_pages = (total + page_size - 1) // page_size

        return NoteListResponse(
            items=[NoteResponse.model_validate(n) for n in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def create_reminder(self, reminder_data: ReminderCreate, user: User) -> ReminderResponse:
        ticket = await self.ticket_repo.get_by_id(reminder_data.ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")
        self._ensure_can_modify(ticket, user)

        reminder = Reminder(
            ticket_id=reminder_data.ticket_id,
            scheduled_time=reminder_data.scheduled_time,
            status="PENDING",
        )
        reminder = await self.reminder_repo.create(reminder)

        return ReminderResponse.model_validate(reminder)

    async def get_reminders(self, ticket_id: int, user: User) -> list[ReminderResponse]:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise NotFoundException("Ticket not found")
        self._ensure_can_view(ticket, user)

        reminders = await self.reminder_repo.get_by_ticket(ticket_id)
        return [ReminderResponse.model_validate(r) for r in reminders]