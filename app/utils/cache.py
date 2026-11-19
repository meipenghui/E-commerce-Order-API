"""Async JSON cache helpers implementing the storage half of cache-aside."""

import json
from typing import Any

from pydantic import BaseModel
from redis.asyncio import Redis

ORDER_DETAIL_CACHE_PREFIX = "order:detail:"


def order_detail_cache_key(order_no: str) -> str:
    """Return the Redis key for one order detail snapshot."""
    return f"{ORDER_DETAIL_CACHE_PREFIX}{order_no}"


def _serialize(value: Any) -> str:
    """Serialize supported values to a JSON string."""
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def get_cache(redis: Redis, key: str) -> str | None:
    """Return the raw JSON string for ``key``, or ``None`` on a cache miss."""
    return await redis.get(key)


async def set_cache(
    redis: Redis,
    key: str,
    value: Any,
    ttl_seconds: int,
) -> None:
    """Serialize ``value`` as JSON and write it with a TTL."""
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be greater than zero")

    await redis.set(key, _serialize(value), ex=ttl_seconds)


async def delete_cache(redis: Redis, key: str) -> int:
    """Delete ``key`` and return the number of removed keys."""
    return await redis.delete(key)
