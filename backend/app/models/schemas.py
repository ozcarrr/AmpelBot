"""
Data transfer objects and Pydantic validation models for AmpelBot.
Partitions public buyer schemas from internal seller margin models.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict

TrafficLight = Literal["RED", "YELLOW", "GREEN"]


class ProductPublic(BaseModel):
    """Public product catalog record excluding internal seller pricing thresholds."""
    model_config = ConfigDict(frozen=True)

    sku: str = Field(..., description="Unique product SKU identifier")
    name: str = Field(..., description="Descriptive product title")
    description: str = Field(..., description="Buyer-facing product description")
    retail_price: float = Field(..., description="Standard list price in USD", ge=0.01)
    currency: str = Field(default="USD", description="Currency ISO-4217 code")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(default=True, description="Inventory availability flag")


class ProductInternal(ProductPublic):
    """
    Internal product model containing proprietary pricing thresholds.
    Excluded from public serialization.
    """
    target_price: float = Field(..., description="Optimal target sale price")
    floor_price: float = Field(..., description="Strict minimum seller margin floor")
    negotiation_notes: str = Field(..., description="Internal merchant negotiation parameters")

    def to_public(self) -> ProductPublic:
        return ProductPublic(
            sku=self.sku,
            name=self.name,
            description=self.description,
            retail_price=self.retail_price,
            currency=self.currency,
            category=self.category,
            in_stock=self.in_stock,
        )


class MarginValidationResult(BaseModel):
    """Evaluation result emitted by the margin firewall."""
    is_valid: bool
    sku: str
    proposed_price: float
    retail_price: float
    floor_price: float
    target_price: Optional[float] = None
    discount_amount: float
    discount_percent: float
    reason: str

    @property
    def composite_retail(self) -> float:
        return self.retail_price

    @property
    def composite_floor(self) -> float:
        return self.floor_price

    @property
    def composite_target(self) -> Optional[float]:
        return self.target_price


class NegotiationLLMOutput(BaseModel):
    """Output schema for negotiation turn inference."""
    reply_message: str = Field(..., description="Merchant response message")
    traffic_light: TrafficLight = Field(..., description="Negotiation state: RED, YELLOW, or GREEN")
    counter_offer_price: Optional[float] = Field(default=None, description="Counter-offer price in USD")
    agreed_price: Optional[float] = Field(default=None, description="Agreed sale price in USD (GREEN only)")
    reasoning_summary: str = Field(..., description="Internal decision rationale")
    bundled_skus: Optional[List[str]] = Field(default=None, description="Unique SKUs participating in bundle deal")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    traffic_light: Optional[TrafficLight] = None
    counter_offer_price: Optional[float] = None
    agreed_price: Optional[float] = None
    reasoning_summary: Optional[str] = None
    bundled_skus: Optional[List[str]] = None
    timestamp: str


class ChatMessageRequest(BaseModel):
    session_id: str = Field(..., description="Unique conversation session identifier")
    sku: str = Field(..., description="Catalog SKU identifier")
    user_message: str = Field(..., description="Buyer negotiation message")
    bundled_skus: Optional[List[str]] = Field(default=None, description="Optional bundle context SKUs")


class ChatMessageResponse(BaseModel):
    session_id: str
    sku: str
    reply_message: str
    traffic_light: TrafficLight
    counter_offer_price: Optional[float] = None
    agreed_price: Optional[float] = None
    reasoning_summary: str
    deal_token: Optional[str] = Field(default=None, description="Cryptographic HMAC deal token on GREEN")
    deal_locked: bool = False
    bundled_skus: Optional[List[str]] = None
    turns_count: int = 1


class ChatSessionResponse(BaseModel):
    session_id: str
    sku: Optional[str] = None
    product_name: Optional[str] = None
    retail_price: Optional[float] = None
    history: List[ChatMessage] = []
    traffic_light: TrafficLight = "YELLOW"
    deal_locked: bool = False
    agreed_price: Optional[float] = None
    deal_token: Optional[str] = None
    bundled_skus: Optional[List[str]] = None
    created_at: str
    updated_at: str


class CreateOrderRequest(BaseModel):
    sku: str = Field(..., description="Product SKU code or canonical bundle SKU (e.g. AMP-01+AMP-03)")
    negotiated_price: float = Field(..., description="Agreed sale price in USD", gt=0)
    buyer_notes: Optional[str] = Field(default=None, description="Transaction notes")
    deal_token: Optional[str] = Field(default=None, description="HMAC deal token")
    session_id: Optional[str] = Field(default=None, description="Associated session ID")
    bundled_skus: Optional[List[str]] = Field(default=None, description="Explicit bundle SKU list")


class CreateOrderResponse(BaseModel):
    order_id: str
    status: str
    approval_url: Optional[str] = None
    sku: str
    product_name: str
    retail_price: float
    negotiated_price: float
    savings_amount: float
    currency: str = "USD"
    created_at: str
    bundled_skus: Optional[List[str]] = None


class CaptureOrderResponse(BaseModel):
    order_id: str
    status: str
    payer_id: Optional[str] = None
    payer_email: Optional[str] = None
    capture_id: Optional[str] = None
    amount_captured: float
    currency: str = "USD"
    captured_at: str
