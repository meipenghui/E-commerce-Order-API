"""Celery tasks for asynchronous order notifications."""

import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.notify.send_payment_success_notify")
def send_payment_success_notify(order_no: str) -> str:
    """Log a payment-success notification from a Celery worker."""
    message = f"订单 {order_no} 支付成功，通知已发送"
    logger.info(message)
    return message
