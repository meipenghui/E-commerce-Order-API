"""Product catalog and SKU endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_admin_user, get_db
from app.models.product import Product
from app.models.sku import SKU
from app.models.user import User
from app.schemas.product import ProductCreate, ProductOut

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "/",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product with nested SKUs",
)
async def create_product(
    payload: ProductCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(get_current_admin_user)],
) -> Product:
    """Create a product and all supplied SKUs in one transaction."""
    product = Product(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    product.skus = [
        SKU(
            sku_code=item.sku_code,
            price=item.price,
            available_stock=item.available_stock,
        )
        for item in payload.skus
    ]
    db.add(product)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SKU code already exists",
        ) from exc

    created = await db.scalar(
        select(Product)
        .options(selectinload(Product.skus))
        .where(Product.id == product.id)
    )
    if created is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Product could not be loaded after creation",
        )
    return created


@router.get(
    "/",
    response_model=list[ProductOut],
    summary="List products with pagination",
)
async def list_products(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[Product]:
    """Return one page of products and their SKUs."""
    statement = (
        select(Product)
        .options(selectinload(Product.skus))
        .order_by(Product.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.scalars(statement)
    return list(result.all())


@router.get(
    "/{product_id}",
    response_model=ProductOut,
    summary="Get product details",
)
async def get_product(
    product_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Product:
    """Return a product and its SKUs by primary key."""
    product = await db.scalar(
        select(Product)
        .options(selectinload(Product.skus))
        .where(Product.id == product_id)
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return product
