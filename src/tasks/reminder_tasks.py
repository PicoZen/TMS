from datetime import datetime
from celery import shared_task
from sqlalchemy import select, and_, create_engine
from sqlalchemy.orm import sessionmaker

from src.common.config import settings
from src.common.logging import get_logger, BackgroundTaskLogger
from src.common.models import Notification, Reminder, ReminderStatus, Ticket, TicketStatus

logger = get_logger(__name__)


def _get_sync_engine():
    """Get sync engine for Celery tasks, handling test mode."""
    db_url = settings.database_url
    # Use SQLite for tests
    if "sqlite" in db_url:
        # Convert async SQLite URL to sync
        sync_url = db_url.replace("sqlite+aiosqlite://", "sqlite://")
    else:
        sync_url = db_url.replace("postgresql+asyncpg", "postgresql")
    
    return create_engine(sync_url, pool_pre_ping=True)


SyncSessionLocal = sessionmaker(bind=create_engine(
    settings.database_url.replace("postgresql+asyncpg", "postgresql").replace("sqlite+aiosqlite://", "sqlite://"),
    pool_pre_ping=True
))


@shared_task(
    bind=True,
    name="src.tasks.reminder_tasks.process_reminders_task",
    queue="reminders",
)
def process_reminders_task(self) -> dict:
    """Process all pending reminders that are due"""
    task_logger = BackgroundTaskLogger("celery_reminder_processing")
    task_logger.started()

    session = SyncSessionLocal()
    try:
        now = datetime.utcnow()

        result = session.execute(
            select(Reminder).where(
                and_(
                    Reminder.status == ReminderStatus.PENDING,
                    Reminder.scheduled_time <= now,
                )
            )
        )
        reminders = result.scalars().all()

        task_logger.progress("found_pending_reminders", count=len(reminders))

        processed = 0
        for reminder in reminders:
            try:
                _process_reminder(session, reminder)
                processed += 1
            except Exception as e:
                task_logger.failed(e, reminder_id=reminder.id)
                reminder.status = ReminderStatus.CANCELLED

        session.commit()
        task_logger.completed(processed=processed)
        return {"status": "success", "processed": processed}

    except Exception as e:
        session.rollback()
        task_logger.failed(e)
        return {"status": "error", "error": str(e)}
    finally:
        session.close()


def _process_reminder(session, reminder: Reminder) -> None:
    """Process a single reminder"""
    ticket = session.execute(
        select(Ticket).where(Ticket.id == reminder.ticket_id)
    ).scalar_one_or_none()

    if not ticket:
        reminder.status = ReminderStatus.CANCELLED
        return

    if ticket.status == TicketStatus.RESOLVED:
        reminder.status = ReminderStatus.CANCELLED
        return

    notification = Notification(
        ticket_id=reminder.ticket_id,
        message=f"Reminder: Ticket '{ticket.title}' needs attention",
    )
    session.add(notification)

    reminder.status = ReminderStatus.FIRED
