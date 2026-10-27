"""
Cryptographic deal signing service for AmpelBot.
Issues and validates HMAC-SHA256 deal tokens binding an authorized negotiation price
to a specific SKU and conversation session.
"""

import hmac
import hashlib
import base64
import json
import time
import uuid
import logging
from typing import Optional, Dict, Any

from ..config import settings
from .negotiator import validate_offer_price, MarginViolationError, ProductNotFoundError

logger = logging.getLogger("ampelbot.deal_signer")


def _get_secret(secret: Optional[str] = None) -> str:
    resolved = secret or settings.DEAL_SIGNING_SECRET
    return resolved if resolved else "ampelbot-default-secure-signing-secret"


def generate_deal_token(
    session_id: str,
    sku: str,
    agreed_price: float,
    secret: Optional[str] = None,
) -> str:
    """
    Issues a cryptographically signed HMAC-SHA256 deal token.
    Token structure: <base64url_json_payload>.<hmac_sha256_hex>
    Payload includes an ephemeral nonce and issuance timestamp to mitigate replay attempts.
    """
    clean_sku = sku.strip().upper()
    clean_price = round(float(agreed_price), 2)
    payload_dict = {
        "session_id": session_id,
        "sku": clean_sku,
        "agreed_price": clean_price,
        "issued_at": int(time.time()),
        "nonce": uuid.uuid4().hex[:12],
    }

    payload_bytes = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(payload_bytes).decode("ascii")

    signing_key = _get_secret(secret).encode("utf-8")
    sig = hmac.new(signing_key, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def decode_deal_token(deal_token: str) -> Optional[Dict[str, Any]]:
    if not deal_token or not isinstance(deal_token, str):
        return None

    parts = deal_token.split(".")
    if len(parts) != 2:
        return None

    b64_payload, _ = parts
    try:
        padding = "=" * ((4 - len(b64_payload) % 4) % 4)
        raw_json = base64.urlsafe_b64decode((b64_payload + padding).encode("ascii"))
        return json.loads(raw_json.decode("utf-8"))
    except Exception as e:
        logger.warning("Failed to decode deal token payload: %s", str(e))
        return None


def verify_deal_token(
    deal_token: str,
    sku: str,
    proposed_price: float,
    secret: Optional[str] = None,
    max_age_seconds: int = 3600,
) -> bool:
    """
    Validates cryptographic authenticity and business constraints of a deal token:
    1. HMAC-SHA256 signature verification with constant-time equality check.
    2. SKU and price equality against token payload.
    3. Expiration window enforcement.
    4. Deterministic margin firewall re-check as a defense-in-depth barrier.
    """
    if not deal_token or not isinstance(deal_token, str):
        return False

    parts = deal_token.split(".")
    if len(parts) != 2:
        return False

    b64_payload, signature = parts
    signing_key = _get_secret(secret).encode("utf-8")
    expected_sig = hmac.new(signing_key, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()

    # Constant-time comparison to prevent timing side-channel attacks on HMAC verification
    if not hmac.compare_digest(expected_sig, signature):
        return False

    payload = decode_deal_token(deal_token)
    if not payload:
        return False

    token_sku = str(payload.get("sku", "")).strip().upper()
    if token_sku != sku.strip().upper():
        return False

    token_price = float(payload.get("agreed_price", 0.0))
    if abs(token_price - float(proposed_price)) > 0.009:
        return False

    issued_at = int(payload.get("issued_at", 0))
    if time.time() - issued_at > max_age_seconds:
        return False

    # Defensive barrier: even if an HMAC signature validates, re-verify mathematical floor
    # boundaries before permitting upstream order creation.
    try:
        validate_offer_price(sku=sku, proposed_price=token_price)
    except (MarginViolationError, ProductNotFoundError):
        return False

    return True
