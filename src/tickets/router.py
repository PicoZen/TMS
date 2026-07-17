from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user, get_current_admin_user
from src.auth.models import User
from src.common.database import get_db
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
from src.tickets.service import TicketService

router = APIRouter(prefix="/tickets", tags=["tickets"])


def get_ticket_service(session: AsyncSession = Depends(get_db)) -> TicketService:
    return TicketService(session)


@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    ticket_data: TicketCreate,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    return await service.create_ticket(ticket_data, current_user)


@router.get("", response_model=TicketListResponse)
async def search_tickets(
    status: str | None = Query(None, pattern="^(OPEN|IN_PROGRESS|RESOLVED)$"),
    priority: str | None = Query(None, pattern="^(LOW|MEDIUM|HIGH)$"),
    category: str | None = Query(None, pattern="^(TECHNICAL|ACCOUNT|BILLING|OTHER)$"),
    assignee_id: int | None = None,
    keyword: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    from datetime import datetime

    params = TicketSearchParams(
        status=status,
        priority=priority,
        category=category,
        assignee_id=assignee_id,
        keyword=keyword,
        created_after=datetime.fromisoformat(created_after) if created_after else None,
        created_before=datetime.fromisoformat(created_before) if created_before else None,
        page=page,
        page_size=page_size,
    )
    return await service.search_tickets(params, current_user)


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: int,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    return await service.get_ticket(ticket_id, current_user)


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: int,
    update_data: TicketUpdate,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    return await service.update_ticket(ticket_id, update_data, current_user)


@router.post("/{ticket_id}/assign", response_model=TicketResponse)
async def assign_ticket(
    ticket_id: int,
    assign_data: TicketAssign,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_admin_user),
):
    return await service.assign_ticket(ticket_id, assign_data, current_user)


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(
    ticket_id: int,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_admin_user),
):
    await service.delete_ticket(ticket_id, current_user)


# Notes
@router.post("/{ticket_id}/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def add_note(
    ticket_id: int,
    note_data: NoteCreate,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    return await service.add_note(ticket_id, note_data, current_user)


@router.get("/{ticket_id}/notes", response_model=NoteListResponse)
async def get_notes(
    ticket_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    return await service.get_notes(ticket_id, current_user, page, page_size)


# Reminders
@router.post("/{ticket_id}/reminders", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    ticket_id: int,
    reminder_data: ReminderCreate,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    reminder_data.ticket_id = ticket_id
    return await service.create_reminder(reminder_data, current_user)


@router.get("/{ticket_id}/reminders", response_model=list[ReminderResponse])
async def get_reminders(
    ticket_id: int,
    service: TicketService = Depends(get_ticket_service),
    current_user: User = Depends(get_current_active_user),
):
    return await service.get_reminders(ticket_id, current_user)