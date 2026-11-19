"""Environment-backed application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "E-commerce Order API"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)

    database_url: str
    db_pool_size: int = Field(default=10, gt=0)
    db_max_overflow: int = Field(default=20, ge=0)
    db_pool_recycle: int = Field(default=1800, gt=0)
    db_echo: bool = False

    redis_url: str
    redis_max_connections: int = Field(default=50, gt=0)
    order_cache_ttl: int = Field(default=600, gt=0)
    celery_broker_url: str
    celery_result_backend: str
    order_timeout_seconds: int = Field(default=1800, gt=0)

    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Reject synchronous or unsupported database URLs early."""
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must start with postgresql+asyncpg://"
            )
        return value

    @field_validator(
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
    )
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        """Require redis:// or rediss:// URLs for Redis-backed services."""
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("Redis URLs must start with redis:// or rediss://")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        """Require a secret long enough for HMAC signing."""
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return one process-wide settings instance."""
    return Settings()


settings = get_settings()
