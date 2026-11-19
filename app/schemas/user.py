"""Pydantic v2 schemas for user registration and authentication."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole


class UserCreate(BaseModel):
    """Registration payload; the plaintext password is never persisted."""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=72)
    email: EmailStr = Field(max_length=320)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        """Reject whitespace-only usernames and store a trimmed value."""
        username = value.strip()
        if not username:
            raise ValueError("Username cannot be blank")
        return username

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        """Store e-mail addresses in a canonical lowercase form."""
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def validate_bcrypt_length(cls, value: str) -> str:
        """Reject passwords that bcrypt would silently truncate."""
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class UserOut(BaseModel):
    """Public user representation that excludes password material."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    """OAuth2-compatible bearer token response."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
