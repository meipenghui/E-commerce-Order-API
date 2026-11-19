"""Celery task for automatically cancelling unpaid orders."""

import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.services.order import (
    InvalidOrderStateError,
    OrderNotFoundError,
    cancel_order,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.order_timeout.cancel_unpaid_order_task")
def cancel_unpaid_order_task(order_no: str) -> str:
    """Cancel an unpaid order after the configured timeout expires."""
    return asyncio.run(_cancel_unpaid_order(order_no))


async def _cancel_unpaid_order(order_no: str) -> str:
    """Check the latest database state and cancel only pending orders."""
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)

    try:
        async with session_factory() as session:
            status = await session.scalar(
                select(Order.status).where(Order.order_no == order_no)
            )
            if status is None:
                logger.warning(
                    "Timeout task found no order %s",
                    order_no,
                )
                return "not_found"

            if status != OrderStatus.PENDING_PAYMENT:
                logger.info(
                    "Skipping timeout cancellation for order %s with status %s",
                    order_no,
                    status.value,
                )
                return f"skipped:{status.value}"

            try:
                await cancel_order(
                    session,
                    redis,
                    order_no,
                    operator="system:order_timeout",
                )
            except (OrderNotFoundError, InvalidOrderStateError):
                logger.info(
                    "Order %s changed state before timeout cancellation",
                    order_no,
                )
                return "skipped:state_changed"

            logger.info("Order %s cancelled automatically after timeout", order_no)
            return "cancelled"
    finally:
        await redis.aclose()
        await engine.dispose()
