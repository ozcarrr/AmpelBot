"""
Chat negotiation API routes for AmpelBot.
Handles conversational turn processing, state machine transitions, and deal token issuance.
"""

from fastapi import APIRouter, HTTPException, status
from ..models.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionResponse,
)
from ..models.inventory import get_internal_product
from ..services.session_store import session_store
from ..services.negotiator import negotiate_turn, ProductNotFoundError
from ..services.deal_signer import generate_deal_token
from ..services.telemetry import telemetry_store

router = APIRouter(prefix="/api/chat", tags=["Chat & Negotiation"])


@router.post(
    "/message",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Process negotiation turn",
)
async def send_chat_message(payload: ChatMessageRequest):
    sku = payload.sku.strip().upper()
    product = get_internal_product(sku)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "PRODUCT_NOT_FOUND", "message": f"Product with SKU '{sku}' not found."},
        )

    session_data = session_store.get_or_create_session(session_id=payload.session_id, sku=sku)

    history_for_llm = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in session_data.get("history", [])
    ]

    try:
        decision = await negotiate_turn(
            session_id=payload.session_id,
            sku=sku,
            user_message=payload.user_message,
            conversation_history=history_for_llm,
        )
    except ProductNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "NEGOTIATION_ENGINE_ERROR", "message": str(e)},
        )

    deal_token = None
    deal_locked = False
    token_skus = decision.bundled_skus if (decision.bundled_skus and len(decision.bundled_skus) > 1) else sku
    if decision.traffic_light == "GREEN" and decision.agreed_price is not None:
        deal_token = generate_deal_token(
            session_id=payload.session_id,
            sku=token_skus,
            agreed_price=decision.agreed_price,
        )
        deal_locked = True

    updated_session = session_store.record_turn(
        session_id=payload.session_id,
        user_text=payload.user_message,
        llm_output=decision,
        deal_token=deal_token,
    )

    telemetry_store.record_turn(
        session_id=payload.session_id,
        sku=sku,
        user_message=payload.user_message,
        decision=decision,
        deal_token=deal_token,
        bundled_skus=decision.bundled_skus,
    )

    turns_count = len(updated_session["history"]) // 2

    return ChatMessageResponse(
        session_id=payload.session_id,
        sku=sku,
        reply_message=decision.reply_message,
        traffic_light=decision.traffic_light,
        counter_offer_price=decision.counter_offer_price,
        agreed_price=decision.agreed_price,
        reasoning_summary=decision.reasoning_summary,
        deal_token=deal_token,
        deal_locked=deal_locked,
        bundled_skus=decision.bundled_skus,
        turns_count=turns_count,
    )


@router.get(
    "/session/{session_id}",
    response_model=ChatSessionResponse,
    summary="Get conversation session state",
)
def get_chat_session(session_id: str):
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "SESSION_NOT_FOUND", "message": f"Session '{session_id}' not found."},
        )
    return session
