"""Celery application configuration backed by Redis."""

import sys

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "ecommerce_order_api",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.notify",
        "app.tasks.order_timeout",
    ],
)

celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_expires=3600,
    result_serializer="json",
    task_serializer="json",
    task_track_started=True,
    timezone="UTC",
)

if sys.platform == "win32":
    celery_app.conf.update(worker_pool="solo")


@celery_app.task(name="app.tasks.celery_app.ping")
def ping() -> str:
    """Minimal task used to verify worker and broker connectivity."""
    return "pong"
