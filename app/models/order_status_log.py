"""Order status transition log ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.order import OrderStatus, order_status_enum

if TYPE_CHECKING:
    from app.models.order import Order


class OrderStatusLog(Base):
    """An immutable record of one order status transition."""

    __tablename__ = "order_status_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(
        order_status_enum,
        nullable=True,
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        order_status_enum,
        nullable=False,
    )
    operator: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    order: Mapped["Order"] = relationship(back_populates="status_logs")
