"""
Smoke & Integration Tests for Phase 3:
Storefront HTML static mounting, Public Client Config endpoint, and AG Grid Merchant Telemetry.
"""

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_root_serves_storefront_index_html():
    """Verify GET / successfully serves the zero-build index.html with all required components."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text
    assert "AmpelBot" in html
    assert "ampel-housing" in html
    assert "paypal-button-container" in html
    assert "ag-grid-telemetry" in html
    assert "merchant-audit-section" in html


def test_static_assets_served_correctly():
    """Verify static CSS and JS assets are served cleanly by FastAPI StaticFiles."""
    css_res = client.get("/css/style.css")
    assert css_res.status_code == 200
    assert "ampel-lens" in css_res.text

    js_app_res = client.get("/js/app.js")
    assert js_app_res.status_code == 200
    assert "AppState" in js_app_res.text

    js_paypal_res = client.get("/js/paypal_sdk.js")
    assert js_paypal_res.status_code == 200
    assert "PayPalSDKManager" in js_paypal_res.text


def test_public_config_endpoint_security():
    """
    Verify GET /api/config/public returns required client attributes
    while strictly protecting secrets (client_secret, private API keys, deal secret).
    """
    response = client.get("/api/config/public")
    assert response.status_code == 200
    data = response.json()

    # Required public keys
    assert "paypal_client_id" in data
    assert "currency" in data
    assert "llm_provider" in data
    assert "is_paypal_configured" in data
    assert "require_deal_lock" in data

    # Strict security check: NO secrets leaked over JSON
    json_str = response.text.lower()
    assert "client_secret" not in json_str
    assert "secret" not in json_str
    assert "api_key" not in json_str
    assert "floor_price" not in json_str


def test_merchant_telemetry_endpoint():
    """Verify GET /api/merchant/telemetry returns summary metrics and structured events for AG Grid."""
    response = client.get("/api/merchant/telemetry")
    assert response.status_code == 200
    data = response.json()

    assert "summary" in data
    assert "events" in data

    summary = data["summary"]
    assert "total_negotiations" in summary
    assert "deals_closed" in summary
    assert "attacks_blocked" in summary
    assert "revenue_unlocked" in summary

    events = data["events"]
    assert isinstance(events, list)
    assert len(events) >= 1

    first_event = events[0]
    required_fields = [
        "id",
        "timestamp",
        "session_id",
        "sku",
        "retail_price",
        "traffic_light",
        "margin_protected",
        "reasoning_summary",
        "firewall_triggered",
    ]
    for field in required_fields:
        assert field in first_event, f"Missing required telemetry field: {field}"


def test_chat_turn_records_live_telemetry_event():
    """Verify that engaging in chat records a live telemetry event in the audit store."""
    session_id = "telemetry-live-test-01"
    sku = "AMP-02"

    payload = {
        "session_id": session_id,
        "sku": sku,
        "user_message": "Can I get this vintage kit for $85?",
    }
    chat_res = client.post("/api/chat/message", json=payload)
    assert chat_res.status_code == 200

    # Query telemetry
    telemetry_res = client.get("/api/merchant/telemetry")
    assert telemetry_res.status_code == 200
    events = telemetry_res.json()["events"]

    matching = [e for e in events if e.get("session_id") == session_id]
    assert len(matching) >= 1
    assert matching[0]["sku"] == "AMP-02"
    assert matching[0]["buyer_offer"] == 85.0


def test_seed_demo_telemetry_endpoint():
    """Verify POST /api/merchant/seed-demo seeds 5 rich historical rows and returns executive KPIs."""
    response = client.post("/api/merchant/seed-demo")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert len(data["events"]) == 5

    summary = data["summary"]
    assert summary["total_negotiations"] == 5
    assert summary["deals_closed"] == 2
    assert summary["attacks_blocked"] >= 1
    assert summary["revenue_unlocked"] == 190.00
    assert "gmv_locked_captured" in summary
    assert "avg_margin_retained_dollars" in summary
    assert "conversion_funnel" in summary
    assert summary["avg_margin_retained_dollars"] == 10.00  # ($10 keyboard + $10 bundle) / 2
