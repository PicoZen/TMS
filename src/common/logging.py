import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from src.common.config import settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)


def add_request_context(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    request_id = request_id_var.get()
    user_id = user_id_var.get()
    if request_id:
        event_dict["request_id"] = request_id
    if user_id:
        event_dict["user_id"] = user_id
    return event_dict


def add_severity_level(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    event_dict["level"] = method_name.upper()
    return event_dict


def setup_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="ISO")

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        add_request_context,
        add_severity_level,
        structlog.processors.add_log_level,
        timestamper,
    ]

    if settings.debug:
        processors: list[Processor] = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    for logger_name in [
        "uvicorn", "uvicorn.error", "uvicorn.access",
        "sqlalchemy.engine", "sqlalchemy.pool",
        "asyncio", "httpx", "openai", "mistral",
    ]:
        logging.getLogger(logger_name).handlers = []
        logging.getLogger(logger_name).propagate = True

    # Configure asyncio logger for background task debugging
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.setLevel(logging.DEBUG if settings.debug else logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


def get_background_task_logger() -> structlog.BoundLogger:
    """Logger specifically for background tasks with task context"""
    return structlog.get_logger("background_tasks")


class BackgroundTaskLogger:
    """Helper to log background task lifecycle with context"""
    
    def __init__(self, task_name: str):
        self.task_name = task_name
        self.logger = get_background_task_logger()
    
    def started(self, **kwargs):
        self.logger.info("task_started", task=self.task_name, **kwargs)
    
    def completed(self, **kwargs):
        self.logger.info("task_completed", task=self.task_name, **kwargs)
    
    def failed(self, error: Exception, **kwargs):
        self.logger.error("task_failed", task=self.task_name, error=str(error), error_type=type(error).__name__, **kwargs)
    
    def progress(self, message: str, **kwargs):
        self.logger.info("task_progress", task=self.task_name, message=message, **kwargs)