"""create orders and status logs

Revision ID: 8e03ba53a633
Revises: bbec2d24640f
Create Date: 2026-11-18 21:52:57.574887
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8e03ba53a633"
down_revision: str | Sequence[str] | None = "bbec2d24640f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

order_status = postgresql.ENUM(
    "PENDING_PAYMENT",
    "PAID",
    "SHIPPED",
    "COMPLETED",
    "CANCELLED",
    name="order_status",
    create_type=False,
)


def upgrade() -> None:
    order_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            order_status,
            server_default="PENDING_PAYMENT",
            nullable=False,
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_amount >= 0",
            name=op.f("ck_orders_total_amount_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_orders_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_index(
        op.f("ix_orders_order_no"),
        "orders",
        ["order_no"],
        unique=True,
    )
    op.create_index(
        op.f("ix_orders_user_id"),
        "orders",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column(
            "subtotal",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_order_items_quantity_positive"),
        ),
        sa.CheckConstraint(
            "subtotal >= 0",
            name=op.f("ck_order_items_subtotal_non_negative"),
        ),
        sa.CheckConstraint(
            "unit_price >= 0",
            name=op.f("ck_order_items_unit_price_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"],
            ["skus.id"],
            name=op.f("fk_order_items_sku_id_skus"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        sa.UniqueConstraint(
            "order_id",
            "sku_id",
            name="uq_order_items_order_id_sku_id",
        ),
    )
    op.create_index(
        op.f("ix_order_items_order_id"),
        "order_items",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_items_sku_id"),
        "order_items",
        ["sku_id"],
        unique=False,
    )
    op.create_table(
        "order_status_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("from_status", order_status, nullable=True),
        sa.Column("to_status", order_status, nullable=False),
        sa.Column("operator", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_status_logs_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_status_logs")),
    )
    op.create_index(
        op.f("ix_order_status_logs_order_id"),
        "order_status_logs",
        ["order_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_order_status_logs_order_id"),
        table_name="order_status_logs",
    )
    op.drop_table("order_status_logs")
    op.drop_index(op.f("ix_order_items_sku_id"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_order_id"), table_name="order_items")
    op.drop_table("order_items")
    op.drop_index(op.f("ix_orders_user_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_order_no"), table_name="orders")
    op.drop_table("orders")
    order_status.drop(op.get_bind(), checkfirst=True)
