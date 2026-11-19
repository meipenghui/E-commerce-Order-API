"""Reusable FastAPI dependencies for database, Redis, and authentication."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import async_session_factory
from app.models.user import User, UserRole

_redis_pool: ConnectionPool | None = None
_redis_client: Redis | None = None

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix}/login",
    auto_error=False,
    description="JWT access token",
)


async def init_redis() -> None:
    """Create the process-wide Redis pool and verify connectivity."""
    global _redis_client, _redis_pool

    if _redis_client is not None:
        return

    pool = ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
    )
    client = Redis(connection_pool=pool)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        await pool.disconnect()
        raise

    _redis_pool = pool
    _redis_client = client


async def close_redis() -> None:
    """Close the Redis client and release all pooled connections."""
    global _redis_client, _redis_pool

    client = _redis_client
    pool = _redis_pool
    _redis_client = None
    _redis_pool = None

    if client is not None:
        await client.aclose()
    if pool is not None:
        await pool.disconnect()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a request-scoped session with rollback on failure.

    Transaction commits belong at the HTTP/unit-of-work boundary, never inside
    service methods.
    """
    session = async_session_factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_redis() -> Redis:
    """Return the application-scoped asynchronous Redis client."""
    if _redis_client is None:
        raise RuntimeError("Redis client has not been initialized")
    return _redis_client


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve and validate the active user represented by a bearer JWT."""
    if token is None:
        raise _unauthorized("Not authenticated")

    try:
        claims = decode_access_token(token)
    except ExpiredSignatureError as exc:
        raise _unauthorized("Token has expired") from exc
    except InvalidTokenError as exc:
        raise _unauthorized("Could not validate credentials") from exc

    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _unauthorized("Could not validate credentials") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("User is inactive or no longer exists")

    return user


async def get_current_admin_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require an authenticated user with the ADMIN role."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )
    return current_user


def _unauthorized(detail: str) -> HTTPException:
    """Build a consistent bearer-token authentication failure."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
