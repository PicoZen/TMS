from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class TicketBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    customer_email: EmailStr


class TicketCreate(TicketBase):
    pass


class TicketUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(OPEN|IN_PROGRESS|RESOLVED)$")
    priority: Optional[str] = Field(default=None, pattern="^(LOW|MEDIUM|HIGH)$")
    category: Optional[str] = Field(default=None, pattern="^(TECHNICAL|ACCOUNT|BILLING|OTHER)$")
    summary: Optional[str] = None
    manual_triage: Optional[bool] = None


class TicketAssign(BaseModel):
    assignee_id: int


class TicketResponse(TicketBase):
    id: int
    status: str
    priority: str
    category: str
    summary: Optional[str] = None
    manual_triage: bool
    assignee_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TicketSearchParams(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    assignee_id: Optional[int] = None
    keyword: Optional[str] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    page: int = 1
    page_size: int = 20


class TicketListResponse(BaseModel):
    items: list[TicketResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class NoteBase(BaseModel):
    note: str = Field(min_length=1)


class NoteCreate(NoteBase):
    pass


class NoteResponse(NoteBase):
    id: int
    ticket_id: int
    agent_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoteListResponse(BaseModel):
    items: list[NoteResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ReminderBase(BaseModel):
    ticket_id: int
    scheduled_time: datetime


class ReminderCreate(ReminderBase):
    pass


class ReminderResponse(ReminderBase):
    id: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)