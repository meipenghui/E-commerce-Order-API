"""Transactional order creation and idempotency control."""

import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.order_status_log import OrderStatusLog
from app.models.product import Product
from app.models.sku import SKU
from app.services.stock import consume_locked_stock, deduct_stock, release_stock
from app.utils.cache import delete_cache, order_detail_cache_key

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
_PENDING_PREFIX = "pending:"
_ORDER_PREFIX = "order:"
_CENT = Decimal("0.01")


class OrderServiceError(Exception):
    """Base class for expected order-domain failures."""


class DuplicateOrderRequestError(OrderServiceError):
    """The idempotency key is already reserved or in progress."""


class OrderValidationError(OrderServiceError):
    """The requested order lines are invalid."""


class SKUUnavailableError(OrderServiceError):
    """A requested SKU does not exist or its product is inactive."""

    def __init__(self, sku_id: int) -> None:
        self.sku_id = sku_id
        super().__init__(f"SKU {sku_id} is unavailable")


class InsufficientStockError(OrderServiceError):
    """A conditional stock update affected no rows."""

    def __init__(self, sku_id: int) -> None:
        self.sku_id = sku_id
        super().__init__(f"Insufficient stock for SKU {sku_id}")


class OrderConflictError(OrderServiceError):
    """A unique database constraint prevented order creation."""


class OrderNotFoundError(OrderServiceError):
    """No order exists for the requested business order number."""

    def __init__(self, order_no: str) -> None:
        self.order_no = order_no
        super().__init__(f"Order {order_no} was not found")


class InvalidOrderStateError(OrderServiceError):
    """A conditional status update found the order in another state."""

    def __init__(
        self,
        order_no: str,
        current_status: OrderStatus | None,
        target_status: OrderStatus,
    ) -> None:
        self.order_no = order_no
        self.current_status = current_status
        self.target_status = target_status
        current = current_status.value if current_status is not None else "missing"
        super().__init__(
            f"Cannot transition order {order_no} from {current} "
            f"to {target_status.value}"
        )


class StockStateError(OrderServiceError):
    """Persisted locked stock is inconsistent with the order items."""

    def __init__(self, order_no: str, sku_id: int, operation: str) -> None:
        self.order_no = order_no
        self.sku_id = sku_id
        self.operation = operation
        super().__init__(
            f"Could not {operation} locked stock for SKU {sku_id} "
            f"on order {order_no}"
        )


@dataclass(frozen=True, slots=True)
class OrderLineInput:
    """Minimal service-layer order line input."""

    sku_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class OrderCreationResult:
    """Created or idempotently resolved order plus creation flag."""

    order: Order
    created: bool


def _idempotency_redis_key(user_id: int, idempotency_key: str) -> str:
    return f"order:idempotency:{user_id}:{idempotency_key}"


def _generate_order_no() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    random_part = secrets.token_hex(4).upper()
    return f"ORD{timestamp}{random_part}"


def _aggregate_quantities(
    items: Sequence[OrderLineInput],
) -> dict[int, int]:
    quantities: dict[int, int] = {}
    for item in items:
        if item.sku_id <= 0 or item.quantity <= 0:
            raise OrderValidationError(
                "SKU IDs and quantities must be greater than zero"
            )
        quantities[item.sku_id] = (
            quantities.get(item.sku_id, 0) + item.quantity
        )
    if not quantities:
        raise OrderValidationError("An order must contain at least one item")
    return quantities


async def get_order_by_no(
    session: AsyncSession,
    order_no: str,
) -> Order | None:
    """Load an order with items and status logs eager-loaded."""
    return await session.scalar(
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.status_logs),
        )
        .where(Order.order_no == order_no)
    )


async def _resolve_existing_order(
    session: AsyncSession,
    redis: Redis,
    redis_key: str,
    user_id: int,
) -> OrderCreationResult:
    stored_value = await redis.get(redis_key)
    if stored_value is None:
        raise DuplicateOrderRequestError(
            "Idempotency key is being processed; retry shortly"
        )

    prefix, separator, order_no = str(stored_value).partition(":")
    if not separator or prefix not in {"pending", "order"}:
        raise DuplicateOrderRequestError("Idempotency key is already in use")

    order = await get_order_by_no(session, order_no)
    if order is None or order.user_id != user_id:
        raise DuplicateOrderRequestError(
            "Idempotency key request is already being processed"
        )

    if prefix == "pending":
        await _mark_order_completed(redis, redis_key, order_no)
    return OrderCreationResult(order=order, created=False)


async def _mark_order_completed(
    redis: Redis,
    redis_key: str,
    order_no: str,
) -> None:
    try:
        await redis.set(
            redis_key,
            f"{_ORDER_PREFIX}{order_no}",
            ex=IDEMPOTENCY_TTL_SECONDS,
        )
    except RedisError:
        logger.exception(
            "Order %s was committed but its idempotency key could not be finalized",
            order_no,
        )


async def _release_idempotency_key(redis: Redis, redis_key: str) -> None:
    try:
        await redis.delete(redis_key)
    except RedisError:
        logger.exception(
            "Failed to release order idempotency key %s",
            redis_key,
        )


async def _invalidate_order_detail_cache(
    redis: Redis,
    order_no: str,
) -> None:
    """Evict a committed order snapshot, keeping TTL as the failure fallback."""
    try:
        await delete_cache(redis, order_detail_cache_key(order_no))
    except RedisError:
        logger.exception(
            "Order %s was committed but its detail cache could not be evicted",
            order_no,
        )


async def _load_active_skus(
    session: AsyncSession,
    sku_ids: set[int],
) -> dict[int, SKU]:
    result = await session.scalars(
        select(SKU)
        .join(Product, SKU.product_id == Product.id)
        .where(
            SKU.id.in_(sku_ids),
            Product.is_active.is_(True),
        )
    )
    skus_by_id = {sku.id: sku for sku in result.all()}
    missing = sku_ids - skus_by_id.keys()
    if missing:
        raise SKUUnavailableError(min(missing))
    return skus_by_id


async def create_order(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    idempotency_key: str,
    items: Sequence[OrderLineInput],
) -> OrderCreationResult:
    """Create an order atomically with Redis-backed idempotency.

    The idempotency key is reserved before database work. The reservation is
    released on failure, and all stock updates plus order writes share one
    database transaction committed only after every step succeeds.
    """
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise OrderValidationError("X-Idempotency-Key cannot be blank")

    redis_key = _idempotency_redis_key(user_id, normalized_key)
    order_no = _generate_order_no()
    reserved = await redis.set(
        redis_key,
        f"{_PENDING_PREFIX}{order_no}",
        nx=True,
        ex=IDEMPOTENCY_TTL_SECONDS,
    )
    if not reserved:
        return await _resolve_existing_order(
            session,
            redis,
            redis_key,
            user_id,
        )

    try:
        quantities = _aggregate_quantities(items)
        skus_by_id = await _load_active_skus(session, set(quantities))

        order_items: list[OrderItem] = []
        total_amount = Decimal("0.00")
        for sku_id in sorted(quantities):
            sku = skus_by_id[sku_id]
            quantity = quantities[sku_id]
            subtotal = (sku.price * quantity).quantize(_CENT)
            total_amount += subtotal
            order_items.append(
                OrderItem(
                    sku_id=sku_id,
                    quantity=quantity,
                    unit_price=sku.price,
                    subtotal=subtotal,
                )
            )

        for sku_id in sorted(quantities):
            if not await deduct_stock(session, sku_id, quantities[sku_id]):
                raise InsufficientStockError(sku_id)

        order = Order(
            order_no=order_no,
            user_id=user_id,
            status=OrderStatus.PENDING_PAYMENT,
            total_amount=total_amount,
            items=order_items,
            status_logs=[
                OrderStatusLog(
                    from_status=None,
                    to_status=OrderStatus.PENDING_PAYMENT,
                    operator=f"user:{user_id}",
                )
            ],
        )
        session.add(order)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        await _release_idempotency_key(redis, redis_key)
        raise OrderConflictError(
            "Order could not be created because of a conflicting value"
        ) from exc
    except Exception:
        await session.rollback()
        await _release_idempotency_key(redis, redis_key)
        raise

    await _mark_order_completed(redis, redis_key, order_no)
    created_order = await get_order_by_no(session, order_no)
    if created_order is None:
        raise OrderServiceError("Committed order could not be reloaded")

    logger.info("Created order %s for user %s", order_no, user_id)
    return OrderCreationResult(order=created_order, created=True)


async def _transition_order_status(
    session: AsyncSession,
    order_no: str,
    *,
    from_status: OrderStatus,
    to_status: OrderStatus,
    operator: str,
) -> tuple[Order, list[OrderItem]]:
    """Apply one conditional status transition inside the caller's transaction."""
    order = await session.scalar(
        select(Order).where(Order.order_no == order_no)
    )
    if order is None:
        raise OrderNotFoundError(order_no)

    statement = (
        update(Order)
        .where(
            Order.id == order.id,
            Order.status == from_status,
        )
        .values(
            status=to_status,
            updated_at=func.now(),
        )
        .returning(Order.id)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(statement)
    if result.scalar_one_or_none() is None:
        current_status = await session.scalar(
            select(Order.status).where(Order.id == order.id)
        )
        raise InvalidOrderStateError(
            order_no,
            current_status,
            to_status,
        )

    items = list(
        (
            await session.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.id)
            )
        ).all()
    )
    session.add(
        OrderStatusLog(
            order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            operator=operator,
        )
    )
    return order, items


async def _reload_committed_order(
    session: AsyncSession,
    order_no: str,
) -> Order:
    """Reload an order from PostgreSQL after a committed Core UPDATE."""
    session.expire_all()
    order = await get_order_by_no(session, order_no)
    if order is None:
        raise OrderNotFoundError(order_no)
    return order


async def pay_order(
    session: AsyncSession,
    redis: Redis,
    order_no: str,
    *,
    operator: str = "system:payment_callback",
) -> Order:
    """Move PENDING_PAYMENT to PAID and consume the locked inventory.

    The status UPDATE, locked-stock consumption, and status log all share one
    database transaction. Any failure rolls the entire payment transition back.
    """
    try:
        _order, items = await _transition_order_status(
            session,
            order_no,
            from_status=OrderStatus.PENDING_PAYMENT,
            to_status=OrderStatus.PAID,
            operator=operator,
        )
        for item in items:
            if not await consume_locked_stock(
                session,
                item.sku_id,
                item.quantity,
            ):
                raise StockStateError(order_no, item.sku_id, "consume")
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await _invalidate_order_detail_cache(redis, order_no)
    updated_order = await _reload_committed_order(session, order_no)
    logger.info("Order %s transitioned to PAID", order_no)
    return updated_order


async def cancel_order(
    session: AsyncSession,
    redis: Redis,
    order_no: str,
    *,
    operator: str = "system:timeout",
) -> Order:
    """Move PENDING_PAYMENT to CANCELLED and atomically release stock.

    If any per-SKU release fails, the conditional status update and all prior
    releases are rolled back in the same transaction.
    """
    try:
        _order, items = await _transition_order_status(
            session,
            order_no,
            from_status=OrderStatus.PENDING_PAYMENT,
            to_status=OrderStatus.CANCELLED,
            operator=operator,
        )
        for item in items:
            if not await release_stock(
                session,
                item.sku_id,
                item.quantity,
            ):
                raise StockStateError(order_no, item.sku_id, "release")
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await _invalidate_order_detail_cache(redis, order_no)
    updated_order = await _reload_committed_order(session, order_no)
    logger.info("Order %s transitioned to CANCELLED", order_no)
    return updated_order
