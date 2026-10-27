"""
Unit tests for AmpelBot Margin Gatekeeper and Catalog Sanitization.
Verifies deterministic guardrails against prompt injection, negative prices,
sub-floor concessions, and proprietary data leaks.
"""

import math
import pytest
from backend.app.models.inventory import (
    DEMO_INVENTORY,
    get_public_catalog,
    get_public_product,
    get_internal_product,
)
from backend.app.services.negotiator import (
    validate_offer_price,
    MarginViolationError,
    ProductNotFoundError,
)


class TestMarginGatekeeperRules:
    """Test suite for deterministic margin validation rules."""

    def test_valid_retail_price_offer(self):
        """Standard full retail price offer should always pass."""
        result = validate_offer_price("AMP-01", 180.00)
        assert result.is_valid is True
        assert result.proposed_price == 180.00
        assert result.discount_amount == 0.00
        assert result.discount_percent == 0.00

    def test_valid_target_concession(self):
        """Target discounted price should pass with correct discount calculation."""
        result = validate_offer_price("AMP-01", 162.00)
        assert result.is_valid is True
        assert result.proposed_price == 162.00
        assert result.discount_amount == 18.00
        assert result.discount_percent == 10.00

    def test_valid_exact_floor_price(self):
        """Offer exactly equal to hard floor should pass."""
        result = validate_offer_price("AMP-01", 145.00)
        assert result.is_valid is True
        assert result.proposed_price == 145.00
        assert result.discount_amount == 35.00
        assert round(result.discount_percent, 1) == 19.4

    def test_reject_sub_cent_below_floor(self):
        """An offer just 1 cent below hard floor must be strictly rejected."""
        with pytest.raises(MarginViolationError) as exc_info:
            validate_offer_price("AMP-01", 144.99)
        assert exc_info.value.sku == "AMP-01"
        assert exc_info.value.floor_price == 145.00
        assert "Margin Firewall Rejection" in str(exc_info.value)

    def test_reject_prompt_injection_one_dollar(self):
        """Simulate LLM hallucination / prompt injection agreeing to $1.00."""
        with pytest.raises(MarginViolationError) as exc_info:
            validate_offer_price("AMP-01", 1.00)
        assert exc_info.value.sku == "AMP-01"
        assert exc_info.value.proposed_price == 1.00
        assert exc_info.value.floor_price == 145.00

    def test_reject_micro_cent_offer(self):
        """Simulate micro-cent injection attack ($0.01)."""
        with pytest.raises(MarginViolationError):
            validate_offer_price("AMP-02", 0.01)

    def test_reject_zero_dollar_offer(self):
        """Zero dollar freebie requests must be rejected."""
        with pytest.raises(MarginViolationError) as exc_info:
            validate_offer_price("AMP-03", 0.00)
        assert "must be strictly positive" in str(exc_info.value)

    def test_reject_negative_price(self):
        """Negative prices (e.g. paying the buyer) must be rejected."""
        with pytest.raises(MarginViolationError) as exc_info:
            validate_offer_price("AMP-03", -50.00)
        assert "must be strictly positive" in str(exc_info.value)

    def test_reject_nan_and_infinity(self):
        """Math irregularities like NaN or Inf must be safely rejected."""
        with pytest.raises(MarginViolationError):
            validate_offer_price("AMP-01", float("nan"))

        with pytest.raises(MarginViolationError):
            validate_offer_price("AMP-01", float("inf"))

    def test_invalid_sku_not_found(self):
        """Non-existent SKU should raise ProductNotFoundError."""
        with pytest.raises(ProductNotFoundError) as exc_info:
            validate_offer_price("INVALID-SKU-999", 100.00)
        assert "INVALID-SKU-999" in str(exc_info.value)

    def test_all_catalog_demo_products_floors(self):
        """Verify hard floor adherence across all 3 catalog demo products."""
        # AMP-01: Keyboard (Floor: $145.00)
        assert validate_offer_price("AMP-01", 145.00).is_valid
        with pytest.raises(MarginViolationError):
            validate_offer_price("AMP-01", 144.90)

        # AMP-02: Football Kit (Floor: $72.00)
        assert validate_offer_price("AMP-02", 72.00).is_valid
        with pytest.raises(MarginViolationError):
            validate_offer_price("AMP-02", 71.99)

        # AMP-03: DevOps Bundle (Floor: $25.00)
        assert validate_offer_price("AMP-03", 25.00).is_valid
        with pytest.raises(MarginViolationError):
            validate_offer_price("AMP-03", 24.99)


class TestCatalogDataSanitization:
    """Test suite ensuring secret seller margins never leak to clients."""

    def test_public_catalog_does_not_contain_secret_fields(self):
        """Public catalog records must not serialize floor_price or negotiation_notes."""
        catalog = get_public_catalog()
        assert len(catalog) == 3

        for item in catalog:
            item_dict = item.model_dump()
            assert "sku" in item_dict
            assert "retail_price" in item_dict
            # Confidential seller fields must NOT exist in the serialized model
            assert "floor_price" not in item_dict
            assert "target_price" not in item_dict
            assert "negotiation_notes" not in item_dict

    def test_single_public_product_lookup(self):
        """Individual product lookup must return sanitized schema."""
        item = get_public_product("AMP-01")
        assert item is not None
        assert item.sku == "AMP-01"
        assert hasattr(item, "retail_price")
        assert not hasattr(item, "floor_price")
        assert not hasattr(item, "negotiation_notes")

    def test_internal_product_retains_secret_fields(self):
        """Internal model must retain floor rules for the gatekeeper."""
        internal = get_internal_product("AMP-01")
        assert internal is not None
        assert internal.floor_price == 145.00
        assert internal.target_price == 162.00
        assert "Never concede past $145.00" in internal.negotiation_notes
