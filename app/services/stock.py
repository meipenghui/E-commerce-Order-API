"""Atomic stock operations."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sku import SKU


async def deduct_stock(
    session: AsyncSession,
    sku_id: int,
    quantity: int,
) -> bool:
    """Atomically move stock from available to locked.

    The conditional UPDATE and both counter changes execute in one statement.
    The caller owns the transaction boundary and must commit or roll back.
    """
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")

    statement = (
        update(SKU)
        .where(
            SKU.id == sku_id,
            SKU.available_stock >= quantity,
        )
        .values(
            available_stock=SKU.available_stock - quantity,
            locked_stock=SKU.locked_stock + quantity,
        )
        .returning(SKU.id)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None


async def consume_locked_stock(
    session: AsyncSession,
    sku_id: int,
    quantity: int,
) -> bool:
    """Atomically consume locked stock after a successful payment.

    Paid stock is sold and therefore disappears from inventory. The
    conditional UPDATE prevents locked stock from becoming negative.
    """
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")

    statement = (
        update(SKU)
        .where(
            SKU.id == sku_id,
            SKU.locked_stock >= quantity,
        )
        .values(
            locked_stock=SKU.locked_stock - quantity,
        )
        .returning(SKU.id)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None


async def release_stock(
    session: AsyncSession,
    sku_id: int,
    quantity: int,
) -> bool:
    """Atomically return locked stock to available stock.

    The conditional UPDATE and both counter changes execute in one statement,
    so concurrent cancellations cannot over-release inventory.
    """
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")

    statement = (
        update(SKU)
        .where(
            SKU.id == sku_id,
            SKU.locked_stock >= quantity,
        )
        .values(
            locked_stock=SKU.locked_stock - quantity,
            available_stock=SKU.available_stock + quantity,
        )
        .returning(SKU.id)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None
