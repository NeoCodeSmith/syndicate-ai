"""
SYNDICATE AI — Celery Application
File: src/syndicate/execution/celery_app.py
"""

from celery import Celery
from syndicate.app import get_settings

settings = get_settings()

celery_app = Celery(
    "syndicate",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["syndicate.execution.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Concurrency
    worker_concurrency=settings.celery_worker_concurrency,
    # Routing
    task_routes={
        "syndicate.execution.tasks.run_agent": {"queue": "default"},
        "syndicate.execution.tasks.run_priority_agent": {"queue": "priority"},
    },
    # Result expiry
    result_expires=86400,  # 24h
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)
