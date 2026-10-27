"""
Orders API routes for AmpelBot.
Validates deal tokens and creates/captures PayPal Orders V2 transactions.
"""

from fastapi import APIRouter, HTTPException, status
from ..config import settings
from ..models.schemas import (
    CreateOrderRequest,
    CreateOrderResponse,
    CaptureOrderResponse,
)
from ..models.inventory import get_internal_product
from ..services.negotiator import MarginViolationError, ProductNotFoundError
from ..services.paypal_client import paypal_client, PayPalAPIError
from ..services.deal_signer import verify_deal_token
from ..services.session_store import session_store

router = APIRouter(prefix="/api/orders", tags=["Orders"])


@router.post(
    "/create",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create PayPal checkout order with validated pricing",
)
def create_negotiated_order(payload: CreateOrderRequest):
    product = get_internal_product(payload.sku)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "PRODUCT_NOT_FOUND", "message": f"Product with SKU '{payload.sku}' not found."},
        )

    if payload.deal_token:
        is_token_valid = verify_deal_token(
            deal_token=payload.deal_token,
            sku=payload.sku,
            proposed_price=payload.negotiated_price,
        )
        if not is_token_valid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "INVALID_DEAL_TOKEN",
                    "message": "The provided deal_token is invalid, expired, or has been tampered with.",
                },
            )
    elif payload.session_id:
        session = session_store.get_session(payload.session_id)
        is_invalid_session = (
            not session
            or not session.deal_locked
            or session.sku != payload.sku.strip().upper()
            or session.agreed_price is None
            or abs(session.agreed_price - payload.negotiated_price) > 0.009
        )
        if is_invalid_session:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "SESSION_DEAL_NOT_LOCKED",
                    "message": "No locked deal found for this session matching the requested SKU and price.",
                },
            )
    elif settings.REQUIRE_DEAL_LOCK and payload.negotiated_price < product.retail_price:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "DEAL_LOCK_REQUIRED",
                "message": "Discounted orders require an approved deal_token or session_id from AmpelBot.",
            },
        )

    try:
        order_dict = paypal_client.create_order(
            sku=payload.sku,
            negotiated_price=payload.negotiated_price,
        )
        return CreateOrderResponse(**order_dict)

    except MarginViolationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "MARGIN_VIOLATION",
                "message": str(e),
                "sku": e.sku,
                "attempted_price": e.proposed_price,
                "floor_price": e.floor_price,
            },
        )
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "PRODUCT_NOT_FOUND", "message": str(e)},
        )
    except PayPalAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "PAYPAL_API_ERROR", "message": str(e)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_SERVER_ERROR", "message": str(e)},
        )


@router.post(
    "/{order_id}/capture",
    response_model=CaptureOrderResponse,
    summary="Capture authorized PayPal checkout order",
)
def capture_order(order_id: str):
    try:
        capture_dict = paypal_client.capture_order(order_id=order_id)
        return CaptureOrderResponse(**capture_dict)

    except PayPalAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "PAYPAL_CAPTURE_ERROR", "message": str(e)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_SERVER_ERROR", "message": str(e)},
        )
