"""
PayPal Orders V2 REST API client for AmpelBot.
Manages OAuth2 client_credentials token caching, order creation with negotiated line items,
and capture execution against the PayPal Sandbox environment.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import requests

from ..config import settings
from ..models.inventory import get_internal_product
from .negotiator import validate_offer_price, MarginViolationError

logger = logging.getLogger("ampelbot.paypal")


class PayPalAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class PayPalClient:
    def __init__(self):
        self.client_id = settings.PAYPAL_CLIENT_ID
        self.client_secret = settings.PAYPAL_CLIENT_SECRET
        self.base_url = settings.PAYPAL_BASE_URL.rstrip("/")
        self._cached_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    def _get_access_token(self) -> str:
        """
        Retrieves an active OAuth2 Bearer token from PayPal.
        Caches the token until 60 seconds before expiration to prevent mid-flight token expiry.
        """
        if not settings.is_paypal_configured:
            raise PayPalAPIError(
                "PayPal Sandbox credentials are not configured in .env. "
                "Please configure PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET."
            )

        now = datetime.now(timezone.utc)
        if self._cached_token and self._token_expires_at and now < (self._token_expires_at - timedelta(seconds=60)):
            return self._cached_token

        token_url = f"{self.base_url}/v1/oauth2/token"
        try:
            response = requests.post(
                token_url,
                auth=(self.client_id, self.client_secret),
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
                data={"grant_type": "client_credentials"},
                timeout=12,
            )
        except requests.RequestException as e:
            raise PayPalAPIError(f"Network error contacting PayPal OAuth: {str(e)}")

        if response.status_code != 200:
            raise PayPalAPIError(
                f"OAuth authentication failed with HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details=response.text,
            )

        data = response.json()
        self._cached_token = data.get("access_token")
        expires_in = data.get("expires_in", 32400)
        self._token_expires_at = now + timedelta(seconds=expires_in)
        return self._cached_token

    def _get_auth_headers(self) -> Dict[str, str]:
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        }

    def create_order(
        self,
        sku: str,
        negotiated_price: float,
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates an Orders V2 checkout order with authorized negotiated pricing.
        Re-verifies margin firewall parameters before initiating outbound API calls.
        """
        validation = validate_offer_price(sku=sku, proposed_price=negotiated_price)
        product = get_internal_product(sku)

        price_str = f"{validation.proposed_price:.2f}"
        savings_str = f"{validation.discount_amount:.2f}"

        custom_desc = (
            f"AmpelBot Deal: {product.name[:50]}... (Saved ${savings_str} off ${product.retail_price:.2f})"
            if validation.discount_amount > 0
            else f"AmpelBot Order: {product.name[:50]}... (List Price)"
        )

        payload: Dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": product.sku,
                    "description": custom_desc,
                    "custom_id": f"AMPELBOT_{product.sku}",
                    "amount": {
                        "currency_code": "USD",
                        "value": price_str,
                        "breakdown": {
                            "item_total": {
                                "currency_code": "USD",
                                "value": price_str,
                            }
                        },
                    },
                    "items": [
                        {
                            "name": product.name[:127],
                            "unit_amount": {
                                "currency_code": "USD",
                                "value": price_str,
                            },
                            "quantity": "1",
                            "category": "PHYSICAL_GOODS" if "License" not in product.name else "DIGITAL_GOODS",
                            "sku": product.sku,
                        }
                    ],
                }
            ],
            "application_context": {
                "brand_name": "AmpelBot AI Sales",
                "landing_page": "NO_PREFERENCE",
                "user_action": "PAY_NOW",
            },
        }

        if return_url:
            payload["application_context"]["return_url"] = return_url
        if cancel_url:
            payload["application_context"]["cancel_url"] = cancel_url

        orders_url = f"{self.base_url}/v2/checkout/orders"
        headers = self._get_auth_headers()

        try:
            response = requests.post(orders_url, headers=headers, json=payload, timeout=15)
        except requests.RequestException as e:
            raise PayPalAPIError(f"Network error creating PayPal order: {str(e)}")

        if response.status_code not in (200, 201):
            raise PayPalAPIError(
                f"PayPal create_order returned HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details=response.text,
            )

        order_data = response.json()
        approval_link = next(
            (link.get("href") for link in order_data.get("links", []) if link.get("rel") == "approve"),
            None,
        )

        return {
            "order_id": order_data.get("id"),
            "status": order_data.get("status", "CREATED"),
            "approval_url": approval_link,
            "sku": product.sku,
            "product_name": product.name,
            "retail_price": product.retail_price,
            "negotiated_price": validation.proposed_price,
            "savings_amount": validation.discount_amount,
            "currency": "USD",
            "created_at": order_data.get("create_time", datetime.now(timezone.utc).isoformat()),
        }

    def capture_order(self, order_id: str) -> Dict[str, Any]:
        """Captures an authorized PayPal Orders V2 transaction."""
        capture_url = f"{self.base_url}/v2/checkout/orders/{order_id}/capture"
        headers = self._get_auth_headers()

        try:
            response = requests.post(capture_url, headers=headers, json={}, timeout=15)
        except requests.RequestException as e:
            raise PayPalAPIError(f"Network error capturing PayPal order: {str(e)}")

        if response.status_code not in (200, 201):
            raise PayPalAPIError(
                f"PayPal capture_order returned HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                details=response.text,
            )

        capture_data = response.json()
        amount_captured = 0.0
        capture_id = None

        units = capture_data.get("purchase_units", [])
        captures = units[0].get("payments", {}).get("captures", []) if units else []
        if captures:
            capture_id = captures[0].get("id")
            amount_captured = float(captures[0].get("amount", {}).get("value", 0.0))

        payer = capture_data.get("payer", {})

        return {
            "order_id": capture_data.get("id", order_id),
            "status": capture_data.get("status", "COMPLETED"),
            "payer_id": payer.get("payer_id"),
            "payer_email": payer.get("email_address"),
            "capture_id": capture_id,
            "amount_captured": amount_captured,
            "currency": "USD",
            "captured_at": capture_data.get("create_time", datetime.now(timezone.utc).isoformat()),
        }


paypal_client = PayPalClient()
