"""Idempotent simulated third-party payment callback endpoint."""

import asyncio
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis
from app.models.order import OrderStatus
from app.schemas.payment import PaymentCallbackIn, PaymentCallbackOut
from app.services.order import (
    InvalidOrderStateError,
    OrderNotFoundError,
    StockStateError,
    get_order_by_no,
    pay_order,
)
from app.tasks.notify import send_payment_success_notify

logger = logging.getLogger(__name__)

PAYMENT_CALLBACK_TTL_SECONDS = 24 * 60 * 60
_RELEASE_CALLBACK_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

router = APIRouter(prefix="/payments", tags=["payments"])


def _callback_key(order_no: str) -> str:
    return f"pay_callback:{order_no}"


async def _release_callback_lock(
    redis: Redis,
    key: str,
    token: str,
) -> None:
    """Delete only the processing marker owned by this request."""
    try:
        await redis.eval(_RELEASE_CALLBACK_LOCK_SCRIPT, 1, key, token)
    except RedisError:
        logger.exception("Failed to release payment callback key %s", key)


async def _enqueue_payment_notification(order_no: str) -> bool:
    """Dispatch the blocking Celery producer call outside the event loop."""
    try:
        await asyncio.to_thread(
            send_payment_success_notify.delay,
            order_no,
        )
    except Exception:
        logger.exception(
            "Payment succeeded but notification could not be queued for %s",
            order_no,
        )
        return False
    return True


@router.post(
    "/callback",
    response_model=PaymentCallbackOut,
    summary="Handle a simulated successful payment callback",
)
async def payment_callback(
    payload: PaymentCallbackIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> PaymentCallbackOut:
    """Apply a successful payment once and enqueue the notification task."""
    if payload.status.upper() != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only SUCCESS callbacks are supported",
        )

    order = await get_order_by_no(db, payload.order_no)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if order.status == OrderStatus.PAID:
        return PaymentCallbackOut(
            order_no=order.order_no,
            order_status=order.status,
            duplicate=True,
            notification_queued=False,
        )
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order cannot be paid from status {order.status.value}",
        )

    key = _callback_key(payload.order_no)
    token = f"processing:{secrets.token_hex(16)}"
    try:
        acquired = await redis.set(
            key,
            token,
            nx=True,
            ex=PAYMENT_CALLBACK_TTL_SECONDS,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment idempotency service is unavailable",
        ) from exc

    if not acquired:
        current_order = await get_order_by_no(db, payload.order_no)
        if current_order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )
        if current_order.status == OrderStatus.PAID:
            return PaymentCallbackOut(
                order_no=current_order.order_no,
                order_status=current_order.status,
                duplicate=True,
                notification_queued=False,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A payment callback for this order is already in progress",
        )

    try:
        paid_order = await pay_order(
            db,
            redis,
            payload.order_no,
            operator="payment_callback",
        )
    except OrderNotFoundError as exc:
        await _release_callback_lock(redis, key, token)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        ) from exc
    except InvalidOrderStateError as exc:
        await _release_callback_lock(redis, key, token)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except StockStateError as exc:
        await _release_callback_lock(redis, key, token)
        logger.exception("Payment stock reconciliation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment stock reconciliation failed",
        ) from exc
    except Exception:
        await _release_callback_lock(redis, key, token)
        raise

    try:
        await redis.set(
            key,
            f"paid:{paid_order.order_no}",
            ex=PAYMENT_CALLBACK_TTL_SECONDS,
        )
    except RedisError:
        logger.exception(
            "Order %s was paid but callback key finalization failed",
            paid_order.order_no,
        )

    notification_queued = await _enqueue_payment_notification(
        paid_order.order_no
    )
    return PaymentCallbackOut(
        order_no=paid_order.order_no,
        order_status=paid_order.status,
        duplicate=False,
        notification_queued=notification_queued,
    )
