"""
Unit and integration tests for Phase 5: Autonomous AOV Expansion (Multi-SKU Cross-Sell Bundling).
Verifies:
1. Composite retail, target, and floor calculations across catalog items.
2. Hard firewall margin enforcement against sub-composite-floor bundle proposals.
3. Canonical HMAC deal token generation, canonical sorting, and anti-tamper security.
4. PayPal Orders V2 itemized breakdown math (item_total - discount == amount.value).
5. End-to-end conversational turn processing with bundle deal locking.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models.inventory import get_bundle_products
from backend.app.services.negotiator import (
    validate_bundle_offer,
    MarginViolationError,
    MarginValidationResult,
    intercept_and_sanitize_decision,
)
from backend.app.models.schemas import NegotiationLLMOutput
from backend.app.services.deal_signer import (
    canonicalize_skus,
    generate_deal_token,
    verify_deal_token,
    decode_deal_token,
)
from backend.app.services.paypal_client import paypal_client

client = TestClient(app)


class TestBundleMathAndFirewall:
    def test_canonicalize_skus_sorting_and_deduplication(self):
        assert canonicalize_skus(["AMP-03", "AMP-01"]) == "AMP-01+AMP-03"
        assert canonicalize_skus(["AMP-01", "AMP-03", "AMP-01"]) == "AMP-01+AMP-03"
        assert canonicalize_skus("AMP-03+AMP-01") == "AMP-01+AMP-03"
        assert canonicalize_skus("AMP-01") == "AMP-01"

    def test_composite_floor_calculation_amp01_amp03(self):
        # AMP-01: retail 180.00 (Wait, let's verify demo inventory prices)
        products = get_bundle_products(["AMP-01", "AMP-03"])
        expected_retail = sum(p.retail_price for p in products)
        expected_target = sum(p.target_price for p in products)
        expected_floor = sum(p.floor_price for p in products)

        # Validate bundle offer at valid price
        valid_price = expected_floor + 5.0
        result = validate_bundle_offer(["AMP-01", "AMP-03"], valid_price)
        assert isinstance(result, MarginValidationResult)
        assert result.retail_price == expected_retail
        assert result.target_price == expected_target
        assert result.floor_price == expected_floor
        assert result.proposed_price == round(valid_price, 2)
        assert result.discount_amount == round(expected_retail - valid_price, 2)

    def test_composite_floor_enforcement_rejects_sub_floor_bundle(self):
        products = get_bundle_products(["AMP-01", "AMP-03"])
        composite_floor = sum(p.floor_price for p in products)

        # Sub-floor attempt: 1 cent below composite floor
        sub_floor_price = composite_floor - 0.01
        with pytest.raises(MarginViolationError) as exc_info:
            validate_bundle_offer(["AMP-01", "AMP-03"], sub_floor_price)

        err = exc_info.value
        assert err.proposed_price == round(sub_floor_price, 2)
        assert err.floor_price == composite_floor

    def test_intercept_and_sanitize_drops_sub_composite_floor_to_red(self):
        products = get_bundle_products(["AMP-01", "AMP-03"])
        composite_floor = sum(p.floor_price for p in products)
        composite_target = sum(p.target_price for p in products)

        hallucinated_output = NegotiationLLMOutput(
            reply_message="Deal accepted! Both items for $100.00!",
            traffic_light="GREEN",
            counter_offer_price=None,
            agreed_price=100.00,  # Below composite floor
            bundled_skus=["AMP-01", "AMP-03"],
            reasoning_summary="Giving away items below cost.",
        )

        sanitized = intercept_and_sanitize_decision("AMP-01", hallucinated_output)
        assert sanitized.traffic_light == "RED"
        assert sanitized.agreed_price is None
        assert sanitized.counter_offer_price == composite_target
        assert "[SECURITY FIREWALL INTERCEPTION]" in sanitized.reasoning_summary


class TestCryptographicBundleTokens:
    def test_bundle_deal_token_generation_and_verification(self):
        session_id = "bundle-test-sess-01"
        skus = ["AMP-03", "AMP-01"]
        agreed_price = 175.00

        token = generate_deal_token(session_id=session_id, sku=skus, agreed_price=agreed_price)
        assert token is not None

        # Verify decoded payload has canonical sorting
        payload = decode_deal_token(token)
        assert payload["sku"] == "AMP-01+AMP-03"
        assert payload["agreed_price"] == 175.00
        assert payload["bundled_skus"] == ["AMP-01", "AMP-03"]

        # Verification succeeds with list or canonical string
        assert verify_deal_token(token, sku=["AMP-01", "AMP-03"], proposed_price=175.00) is True
        assert verify_deal_token(token, sku=["AMP-03", "AMP-01"], proposed_price=175.00) is True
        assert verify_deal_token(token, sku="AMP-01+AMP-03", proposed_price=175.00) is True

    def test_bundle_token_cannot_be_reused_for_single_sku(self):
        token = generate_deal_token(
            session_id="bundle-test-sess-02",
            sku=["AMP-01", "AMP-03"],
            agreed_price=175.00,
        )
        # Attempting to use bundle token to buy single SKU AMP-01 must fail
        assert verify_deal_token(token, sku="AMP-01", proposed_price=175.00) is False

    def test_single_sku_token_cannot_be_reused_for_bundle(self):
        token = generate_deal_token(
            session_id="bundle-test-sess-03",
            sku="AMP-01",
            agreed_price=150.00,
        )
        assert verify_deal_token(token, sku=["AMP-01", "AMP-03"], proposed_price=150.00) is False

    def test_bundle_token_tampered_price_fails(self):
        token = generate_deal_token(
            session_id="bundle-test-sess-04",
            sku=["AMP-01", "AMP-03"],
            agreed_price=175.00,
        )
        # Attempting to claim lower price
        assert verify_deal_token(token, sku=["AMP-01", "AMP-03"], proposed_price=150.00) is False


class TestPayPalOrdersV2BundleBreakdown:
    def test_itemized_breakdown_math_equality(self, monkeypatch):
        """
        Verifies that purchase_units breakdown adheres strictly to PayPal invariant:
        amount.value == item_total.value - discount.value
        """
        captured_payload = {}

        def mock_post(url, headers, json, timeout):
            non_local_url = url
            captured_payload.update(json)

            class MockResponse:
                status_code = 201

                def json(self):
                    return {
                        "id": "PAYPAL-MOCK-BUNDLE-ORDER",
                        "status": "CREATED",
                        "links": [{"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=MOCK"}],
                        "create_time": "2026-10-26T22:00:00Z",
                    }

            return MockResponse()

        monkeypatch.setattr("requests.post", mock_post)
        monkeypatch.setattr(paypal_client, "_get_access_token", lambda: "mock_token")

        order_res = paypal_client.create_order(
            sku=["AMP-01", "AMP-03"],
            negotiated_price=175.00,
        )

        assert order_res["status"] == "CREATED"
        assert order_res["order_id"] == "PAYPAL-MOCK-BUNDLE-ORDER"
        assert order_res["sku"] == "AMP-01+AMP-03"
        assert order_res["negotiated_price"] == 175.00
        assert order_res["bundled_skus"] == ["AMP-01", "AMP-03"]

        # Verify raw PayPal API payload math
        unit = captured_payload["purchase_units"][0]
        amount_val = float(unit["amount"]["value"])
        item_total_val = float(unit["amount"]["breakdown"]["item_total"]["value"])
        discount_val = float(unit["amount"]["breakdown"]["discount"]["value"])

        # Strict Invariant: item_total - discount == amount.value
        assert round(item_total_val - discount_val, 2) == round(amount_val, 2)
        assert amount_val == 175.00

        # Items list itemized retail prices
        items = unit["items"]
        assert len(items) == 2
        items_sum = sum(float(i["unit_amount"]["value"]) * int(i["quantity"]) for i in items)
        assert round(items_sum, 2) == round(item_total_val, 2)


class TestChatBundleNegotiationFlow:
    def test_bundle_chat_request_transitions_to_green_with_deal_token(self):
        session_id = "bundle-chat-integration-test"

        # Buyer prompts bundle request
        payload = {
            "session_id": session_id,
            "sku": "AMP-01",
            "user_message": "Bundle Request: Include AMP-03 for $175 total",
        }
        res = client.post("/api/chat/message", json=payload)
        assert res.status_code == 200
        data = res.json()

        assert data["traffic_light"] == "GREEN"
        assert data["agreed_price"] == 175.00
        assert data["deal_locked"] is True
        assert data["deal_token"] is not None
        assert data["bundled_skus"] == ["AMP-01", "AMP-03"]

        # Verify session state persistence
        session_res = client.get(f"/api/chat/session/{session_id}")
        assert session_res.status_code == 200
        sess_data = session_res.json()
        assert sess_data["deal_locked"] is True
        assert sess_data["agreed_price"] == 175.00
        assert sess_data["bundled_skus"] == ["AMP-01", "AMP-03"]

    def test_create_order_with_bundle_deal_token(self, monkeypatch):
        session_id = "bundle-order-test-sess"

        # 1. Negotiate bundle deal
        chat_res = client.post("/api/chat/message", json={
            "session_id": session_id,
            "sku": "AMP-01",
            "user_message": "Bundle Request: Include AMP-03 for $175 total",
        })
        token = chat_res.json()["deal_token"]
        assert token is not None

        # 2. Mock PayPal order API
        def mock_create_order(**kwargs):
            return {
                "order_id": "TEST-BUNDLE-ORDER-ID",
                "status": "CREATED",
                "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=TEST",
                "sku": "AMP-01+AMP-03",
                "product_name": "Mock Bundle",
                "retail_price": 229.00,
                "negotiated_price": 175.00,
                "savings_amount": 54.00,
                "currency": "USD",
                "created_at": "2026-10-26T22:00:00Z",
                "bundled_skus": ["AMP-01", "AMP-03"],
            }

        monkeypatch.setattr(paypal_client, "create_order", mock_create_order)

        # 3. Create negotiated order using deal_token
        order_payload = {
            "sku": "AMP-01+AMP-03",
            "negotiated_price": 175.00,
            "deal_token": token,
            "bundled_skus": ["AMP-01", "AMP-03"],
        }
        res = client.post("/api/orders/create", json=order_payload)
        assert res.status_code == 201
        order_data = res.json()
        assert order_data["order_id"] == "TEST-BUNDLE-ORDER-ID"
        assert order_data["negotiated_price"] == 175.00
        assert order_data["bundled_skus"] == ["AMP-01", "AMP-03"]
