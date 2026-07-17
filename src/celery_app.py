from celery import Celery
from src.common.config import settings

import os
IS_TEST = (
    os.environ.get("PYTEST_CURRENT_TEST") is not None 
    or "pytest" in os.environ.get("_", "") 
    or os.environ.get("TESTING") == "true"
)

if IS_TEST:
    broker_url = "memory://"
    result_backend = "rpc://"
    beat_schedule = {}
else:
    broker_url = settings.celery_broker_url
    result_backend = settings.redis_url
    beat_schedule = {
        "process-reminders-every-minute": {
            "task": "src.tasks.reminder_tasks.process_reminders_task",
            "schedule": 60.0,
        },
    }

celery_app = Celery(
    "tms_oc",
    broker=broker_url,
    backend=result_backend,
    include=[
        "src.tasks.reminder_tasks",
        "src.tasks.classification_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule=beat_schedule,
    # Windows compatibility settings
    worker_pool="solo",
    worker_concurrency=1,
)

# Tasks register themselves via @shared_task when their module is imported;
# `include=[...]` above is what makes that import happen for the worker and
# beat processes. No separate registration step needed here.