"""Authenticated order creation, retrieval, and cancellation endpoints."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_redis
from app.core.config import settings
from app.models.order import Order
from app.models.user import User, UserRole
from app.schemas.order import OrderCreate, OrderOut
from app.services.order import (
    DuplicateOrderRequestError,
    InsufficientStockError,
    InvalidOrderStateError,
    OrderConflictError,
    OrderLineInput,
    OrderNotFoundError,
    OrderServiceError,
    OrderValidationError,
    SKUUnavailableError,
    StockStateError,
    cancel_order,
    create_order,
    get_order_by_no,
)
from app.tasks.order_timeout import cancel_unpaid_order_task
from app.utils.cache import (
    delete_cache,
    get_cache,
    order_detail_cache_key,
    set_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post(
    "/",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an order idempotently",
)
async def create_order_endpoint(
    payload: OrderCreate,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(
            alias="X-Idempotency-Key",
            min_length=1,
            max_length=128,
        ),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> Order:
    """Create an order or return the order stored for the same key."""
    try:
        result = await create_order(
            db,
            redis,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            items=[
                OrderLineInput(
                    sku_id=item.sku_id,
                    quantity=item.quantity,
                )
                for item in payload.items
            ],
        )
    except DuplicateOrderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InsufficientStockError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except SKUUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except OrderConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except OrderValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except OrderServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order processing failed",
        ) from exc
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Idempotency service is unavailable",
        ) from exc

    if result.created:
        await _schedule_order_timeout(result.order.order_no)
    else:
        response.status_code = status.HTTP_200_OK
    return result.order


@router.get(
    "/{order_no}",
    response_model=OrderOut,
    summary="Get an order by business order number",
)
async def get_order_endpoint(
    order_no: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OrderOut:
    """Return an order visible only to its owner or an administrator."""
    cache_key = order_detail_cache_key(order_no)
    try:
        cached_order = await get_cache(redis, cache_key)
    except RedisError:
        logger.warning(
            "Order detail cache read failed for %s",
            order_no,
            exc_info=True,
        )
        cached_order = None

    if cached_order is not None:
        try:
            order = OrderOut.model_validate_json(cached_order)
        except ValidationError:
            logger.warning(
                "Ignoring invalid cached order detail for %s",
                order_no,
                exc_info=True,
            )
            try:
                await delete_cache(redis, cache_key)
            except RedisError:
                logger.warning(
                    "Failed to evict invalid order cache %s",
                    cache_key,
                    exc_info=True,
                )
        else:
            _ensure_order_access(order.user_id, current_user, "access")
            logger.info("Order detail cache hit for %s", order_no)
            return order

    logger.info("Order detail cache miss for %s", order_no)
    db_order = await get_order_by_no(db, order_no)
    if db_order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    _ensure_order_access(db_order.user_id, current_user, "access")

    order = OrderOut.model_validate(db_order)
    try:
        await set_cache(
            redis,
            cache_key,
            order,
            settings.order_cache_ttl,
        )
    except RedisError:
        logger.warning(
            "Order detail cache write failed for %s",
            order_no,
            exc_info=True,
        )
    return order


@router.delete(
    "/{order_no}",
    response_model=OrderOut,
    summary="Cancel a pending order as a timeout simulation",
)
async def cancel_order_endpoint(
    order_no: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Order:
    """Cancel a pending order and atomically return its stock."""
    order = await get_order_by_no(db, order_no)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if (
        current_user.role != UserRole.ADMIN
        and order.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to cancel this order",
        )

    try:
        return await cancel_order(
            db,
            redis,
            order_no,
            operator=f"timeout:user:{current_user.id}",
        )
    except OrderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        ) from exc
    except InvalidOrderStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except StockStateError as exc:
        logger.exception("Order cancellation stock rollback failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order cancellation stock reconciliation failed",
        ) from exc


def _ensure_order_access(
    order_user_id: int,
    current_user: User,
    action: str,
) -> None:
    """Enforce owner-or-admin access using a cached or database snapshot."""
    if (
        current_user.role != UserRole.ADMIN
        and order_user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Not allowed to {action} this order",
        )


async def _schedule_order_timeout(order_no: str) -> None:
    """Queue the order-timeout task without blocking the event loop."""
    try:
        await asyncio.to_thread(
            cancel_unpaid_order_task.apply_async,
            args=[order_no],
            countdown=settings.order_timeout_seconds,
        )
    except Exception:
        logger.exception(
            "Order %s was created but its timeout task could not be queued",
            order_no,
        )
    else:
        logger.info(
            "Scheduled timeout cancellation for order %s in %s seconds",
            order_no,
            settings.order_timeout_seconds,
        )
