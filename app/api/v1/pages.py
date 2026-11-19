"""Server-rendered page routes for the browser interface."""

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import settings

router = APIRouter(tags=["pages"], include_in_schema=False)


@router.get("/")
async def index() -> RedirectResponse:
    """Send visitors to the login page for the client-side token check."""
    return RedirectResponse(
        url="/login",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render the login and registration page."""
    return _render_page(request, "login.html")


@router.get("/products", response_class=HTMLResponse)
async def products_page(request: Request) -> HTMLResponse:
    """Render the product catalog page."""
    return _render_page(request, "products.html")


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request) -> HTMLResponse:
    """Render the current user's order list page."""
    return _render_page(request, "orders.html")


def _render_page(request: Request, template_name: str) -> HTMLResponse:
    """Render one page with the application-wide template configuration."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"app_name": settings.app_name},
    )
