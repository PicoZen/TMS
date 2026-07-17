"""Celery task that performs the single, isolated LLM triage call for a
ticket.

Retry strategy: Celery-native, via `self.retry(...)`, not a hand-rolled
sleep loop. Each retry is a brand-new task execution — the ticket is
re-fetched from the DB and the LLM is called again from scratch — so a
transient failure on one attempt (a timeout, a 500 from the provider, a
DB hiccup) can't leave anything half-applied for the next attempt to build
on. Backoff is exponential (base * 2^attempt, capped at a configurable
ceiling) so a provider outage doesn't get hammered with immediate retries.

If every retry is exhausted, the ticket is explicitly marked
classification_status=FAILED and manual_triage=True — the assignment's core
constraint is that the LLM step is "an enhancement, not a hard dependency,"
which has to hold even in the worst case (provider is down for the full
retry window), not just on the happy path.
"""
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.common.config import settings
from src.common.logging import BackgroundTaskLogger, get_logger
from src.common.models import ClassificationStatus, Ticket, TicketCategory, TicketPriority
from src.llm.service import llm_service

logger = get_logger(__name__)


def _sync_db_url() -> str:
    """Celery tasks run outside the FastAPI event loop, so they use a plain
    sync SQLAlchemy engine/session rather than the app's async one."""
    db_url = settings.database_url
    if "sqlite" in db_url:
        return db_url.replace("sqlite+aiosqlite://", "sqlite://")
    return db_url.replace("postgresql+asyncpg", "postgresql")


SyncSessionLocal = sessionmaker(bind=create_engine(_sync_db_url(), pool_pre_ping=True))


def _backoff_seconds(retry_number: int) -> float:
    """Exponential backoff: base * 2^retry_number, capped at the configured
    ceiling. With defaults (base=1.0, max=600): 1s, 2s, 4s, 8s, ... up to 10min."""
    return min(
        settings.llm_retry_backoff_base * (2 ** retry_number),
        settings.llm_retry_backoff_max,
    )


@shared_task(bind=True, queue="classification")
def classify_ticket_task(self, ticket_id: int) -> dict:
    """Classify a single ticket using the configured LLM adapter."""
    attempt = self.request.retries + 1
    task_logger = BackgroundTaskLogger("celery_ticket_classification")
    task_logger.started(ticket_id=ticket_id, task_id=self.request.id, attempt=attempt)

    session = SyncSessionLocal()
    try:
        ticket = session.execute(
            select(Ticket).where(Ticket.id == ticket_id)
        ).scalar_one_or_none()

        if not ticket:
            task_logger.progress("ticket_not_found", ticket_id=ticket_id)
            return {"status": "not_found", "ticket_id": ticket_id}

        ticket.classification_status = ClassificationStatus.PROCESSING
        session.commit()

        classification = llm_service.classify_sync(ticket.title, ticket.description)

        ticket.summary = classification.summary
        ticket.category = TicketCategory(classification.category)
        ticket.priority = TicketPriority(classification.priority)
        ticket.manual_triage = False
        ticket.classification_status = ClassificationStatus.COMPLETED
        session.commit()

        task_logger.completed(ticket_id=ticket_id, classification=classification.model_dump())
        return {"status": "success", "ticket_id": ticket_id}

    except Exception as exc:
        session.rollback()
        task_logger.failed(exc, ticket_id=ticket_id, attempt=attempt)

        try:
            raise self.retry(
                exc=exc,
                countdown=_backoff_seconds(self.request.retries),
                max_retries=settings.llm_max_retries,
            )
        except MaxRetriesExceededError:
            # Every retry failed - fall back to manual triage instead of
            # leaving the ticket stuck at PENDING/PROCESSING forever.
            task_logger.failed(exc, ticket_id=ticket_id, attempt=attempt, final=True)
            ticket = session.execute(
                select(Ticket).where(Ticket.id == ticket_id)
            ).scalar_one_or_none()
            if ticket:
                ticket.classification_status = ClassificationStatus.FAILED
                ticket.manual_triage = True
                ticket.classification_retry_count = attempt
                session.commit()
            return {"status": "manual_triage", "ticket_id": ticket_id}
    finally:
        session.close()
