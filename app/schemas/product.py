"""Pydantic v2 schemas for products and SKUs."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SKUCreate(BaseModel):
    """Initial stock and price for a new SKU."""

    sku_code: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    available_stock: int = Field(default=0, ge=0)

    @field_validator("sku_code")
    @classmethod
    def normalize_sku_code(cls, value: str) -> str:
        """Trim SKU codes and reject blank values."""
        sku_code = value.strip()
        if not sku_code:
            raise ValueError("SKU code cannot be blank")
        return sku_code


class ProductCreate(BaseModel):
    """Product creation payload with optional nested SKU definitions."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    is_active: bool = True
    skus: list[SKUCreate] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Trim product names and reject blank values."""
        name = value.strip()
        if not name:
            raise ValueError("Product name cannot be blank")
        return name

    @field_validator("skus")
    @classmethod
    def ensure_unique_sku_codes(cls, value: list[SKUCreate]) -> list[SKUCreate]:
        """Reject duplicate SKU codes within one product payload."""
        codes = [item.sku_code for item in value]
        if len(codes) != len(set(codes)):
            raise ValueError("SKU codes must be unique within a product")
        return value


class SKUOut(BaseModel):
    """Public SKU representation including stock counters."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_code: str
    price: Decimal
    available_stock: int
    locked_stock: int
    created_at: datetime


class ProductOut(BaseModel):
    """Product detail with all nested SKUs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    skus: list[SKUOut]
