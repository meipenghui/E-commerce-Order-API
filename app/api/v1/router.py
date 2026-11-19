"""Aggregate router for version 1 endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis
from app.api.v1.auth import router as auth_router
from app.api.v1.orders import router as orders_router
from app.api.v1.payments import router as payments_router
from app.api.v1.products import router as products_router

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(auth_router)
router.include_router(orders_router)
router.include_router(payments_router)
router.include_router(products_router)


@router.get("/health", tags=["health"], summary="Check service dependencies")
async def health_check(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, str]:
    """Confirm that the API, PostgreSQL, and Redis are reachable."""
    try:
        await db.execute(text("SELECT 1"))
        await redis.ping()
    except Exception as exc:
        logger.exception("Dependency health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependency health check failed",
        ) from exc

    return {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
    }
