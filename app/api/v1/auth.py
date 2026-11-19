"""User registration, login, and authenticated profile endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, get_db
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserOut

router = APIRouter(tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer account",
)
async def register(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserOut:
    """Create a user after checking unique username and e-mail constraints."""
    existing = await db.scalar(
        select(User).where(
            or_(
                User.username == payload.username,
                User.email == payload.email,
            )
        )
    )
    if existing is not None:
        detail = (
            "Username already registered"
            if existing.username == payload.username
            else "Email already registered"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=await run_in_threadpool(
            hash_password,
            payload.password,
        ),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        ) from exc

    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=Token,
    summary="Exchange credentials for a bearer token",
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Authenticate an active user and return a signed access token."""
    user = await db.scalar(
        select(User).where(User.username == form_data.username.strip())
    )
    credentials_are_valid = user is not None and await run_in_threadpool(
        verify_password,
        form_data.password,
        user.hashed_password,
    )
    if not credentials_are_valid or user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        subject=str(user.id),
        role=user.role.value,
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get(
    "/me",
    response_model=UserOut,
    summary="Return the authenticated user",
)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserOut:
    """Expose a protected endpoint for verifying Swagger authorization."""
    return UserOut.model_validate(current_user)
