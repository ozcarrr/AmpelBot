"""
AmpelBot FastAPI application entrypoint.
Serves negotiation API routes and mounts static frontend assets.
"""

from pathlib import Path
from typing import List
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models.schemas import ProductPublic
from .models.inventory import get_public_catalog, get_public_product
from .routes.orders import router as orders_router
from .routes.chat import router as chat_router
from .routes.merchant import router as merchant_router

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(
    title="AmpelBot AI Sales & Negotiation API",
    description="Micro-negotiation agent with deterministic margin firewalls and PayPal Orders V2 integration.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders_router)
app.include_router(chat_router)
app.include_router(merchant_router)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "online",
        "service": "AmpelBot Backend",
        "paypal_sandbox_configured": settings.is_paypal_configured,
        "paypal_base_url": settings.PAYPAL_BASE_URL,
        "llm_provider": settings.LLM_PROVIDER,
        "gemini_configured": settings.is_gemini_configured,
        "openai_compat_configured": settings.is_openai_compat_configured,
        "products_count": len(get_public_catalog()),
    }


@app.get(
    "/api/products",
    response_model=List[ProductPublic],
    tags=["Products"],
    summary="Get public product catalog (sanitized)",
)
def list_products():
    return get_public_catalog()


@app.get(
    "/api/products/{sku}",
    response_model=ProductPublic,
    tags=["Products"],
    summary="Get single public product by SKU",
)
def get_product(sku: str):
    product = get_public_product(sku)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with SKU '{sku}' not found.",
        )
    return product


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
