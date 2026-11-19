"""Pydantic v2 schemas for order creation and responses."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    """One requested SKU and quantity."""

    sku_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    """Order creation request; prices are always resolved server-side."""

    items: list[OrderItemCreate] = Field(min_length=1, max_length=100)


class OrderItemOut(BaseModel):
    """Persisted order line item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class OrderStatusLogOut(BaseModel):
    """One persisted status transition."""

    model_config = ConfigDict(from_attributes=True)

    from_status: OrderStatus | None
    to_status: OrderStatus
    operator: str
    created_at: datetime


class OrderOut(BaseModel):
    """Order detail with item and status-history snapshots."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    user_id: int
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]
    status_logs: list[OrderStatusLogOut]
