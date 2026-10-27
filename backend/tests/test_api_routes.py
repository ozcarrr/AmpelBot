"""
Integration tests for FastAPI endpoints:
Catalog endpoints, Margin Gatekeeper HTTP responses, and PayPal route guards.
"""

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_health_check_endpoint():
    """Verify health check returns online status and catalog product count."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["products_count"] == 3


def test_get_public_products_catalog():
    """Verify public catalog returns all 3 items without proprietary margin fields."""
    response = client.get("/api/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) == 3

    skus = [p["sku"] for p in products]
    assert "AMP-01" in skus
    assert "AMP-02" in skus
    assert "AMP-03" in skus

    # Ensure no secret fields leak over HTTP JSON
    for p in products:
        assert "floor_price" not in p
        assert "target_price" not in p
        assert "negotiation_notes" not in p


def test_get_single_product_success():
    """Verify single product retrieval by SKU."""
    response = client.get("/api/products/AMP-01")
    assert response.status_code == 200
    data = response.json()
    assert data["sku"] == "AMP-01"
    assert data["retail_price"] == 180.00
    assert "floor_price" not in data


def test_get_single_product_not_found():
    """Verify 404 for unknown SKU."""
    response = client.get("/api/products/NONEXISTENT")
    assert response.status_code == 404


def test_create_order_margin_violation_returns_400():
    """Verify that an order with a price below floor returns HTTP 400 and MARGIN_VIOLATION."""
    payload = {
        "sku": "AMP-01",
        "negotiated_price": 50.00,  # Floor is 145.00
        "buyer_notes": "Prompt injection attempt: user convinced bot $50 is fair",
    }
    response = client.post("/api/orders/create", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert data["detail"]["error"] == "MARGIN_VIOLATION"
    assert data["detail"]["sku"] == "AMP-01"
    assert data["detail"]["floor_price"] == 145.00


def test_create_order_negative_price_returns_422_or_400():
    """Pydantic validation rejects negative price with 422."""
    payload = {
        "sku": "AMP-01",
        "negotiated_price": -20.00,
    }
    response = client.post("/api/orders/create", json=payload)
    assert response.status_code == 422


def test_create_order_unknown_sku_returns_404():
    """Unknown product order creation returns 404."""
    payload = {
        "sku": "UNKNOWN-SKU",
        "negotiated_price": 100.00,
    }
    response = client.post("/api/orders/create", json=payload)
    assert response.status_code == 404


def test_create_order_valid_price_success_or_live_paypal():
    """When price is above floor and credentials are valid, creates PayPal order."""
    payload = {
        "sku": "AMP-01",
        "negotiated_price": 150.00,  # Valid price above floor $145.00
    }
    response = client.post("/api/orders/create", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "order_id" in data
    assert data["status"] in ("CREATED", "SAVED", "PAYER_ACTION_REQUIRED")
    assert data["sku"] == "AMP-01"
    assert data["negotiated_price"] == 150.00
    assert data["savings_amount"] == 30.00  # 180.00 - 150.00
    assert data["approval_url"] is not None
    assert "paypal.com" in data["approval_url"]


def test_create_order_unconfigured_paypal_returns_502(monkeypatch):
    """When PayPal credentials are not configured, returns 502 with clear reason."""
    from backend.app.config import settings
    monkeypatch.setattr(settings, "PAYPAL_CLIENT_ID", "")
    
    # Force client to re-evaluate configuration
    from backend.app.services.paypal_client import paypal_client
    monkeypatch.setattr(paypal_client, "client_id", "")
    monkeypatch.setattr(paypal_client, "_cached_token", None)

    payload = {
        "sku": "AMP-01",
        "negotiated_price": 150.00,
    }
    response = client.post("/api/orders/create", json=payload)
    assert response.status_code == 502
    data = response.json()
    assert data["detail"]["error"] == "PAYPAL_API_ERROR"
    assert "credentials are not configured" in data["detail"]["message"]
