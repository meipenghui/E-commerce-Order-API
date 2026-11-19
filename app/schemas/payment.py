"""Pydantic v2 schemas for simulated payment callbacks."""

from pydantic import BaseModel, Field

from app.models.order import OrderStatus


class PaymentCallbackIn(BaseModel):
    """Third-party callback payload used by the development simulator."""

    order_no: str = Field(min_length=1, max_length=40)
    status: str = Field(min_length=1, max_length=32)


class PaymentCallbackOut(BaseModel):
    """Stable callback result including idempotency metadata."""

    order_no: str
    order_status: OrderStatus
    duplicate: bool
    notification_queued: bool
