"""create products and skus

Revision ID: bbec2d24640f
Revises: c0e8eac523ed
Create Date: 2026-11-18 21:35:11.503051
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "bbec2d24640f"
down_revision: str | Sequence[str] | None = "c0e8eac523ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.create_table(
        "skus",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "available_stock",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "locked_stock",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "available_stock >= 0",
            name=op.f("ck_skus_available_stock_non_negative"),
        ),
        sa.CheckConstraint(
            "locked_stock >= 0",
            name=op.f("ck_skus_locked_stock_non_negative"),
        ),
        sa.CheckConstraint(
            "price >= 0",
            name=op.f("ck_skus_price_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_skus_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skus")),
    )
    op.create_index(
        op.f("ix_skus_product_id"),
        "skus",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_skus_sku_code"),
        "skus",
        ["sku_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_skus_sku_code"), table_name="skus")
    op.drop_index(op.f("ix_skus_product_id"), table_name="skus")
    op.drop_table("skus")
    op.drop_table("products")
