"""
Merchant telemetry and public configuration endpoints for AmpelBot.
"""

from fastapi import APIRouter, status
from ..config import settings
from ..services.telemetry import telemetry_store

router = APIRouter(prefix="/api", tags=["Merchant & Config"])


@router.get(
    "/config/public",
    status_code=status.HTTP_200_OK,
    summary="Get sanitized runtime configuration for client initialization",
)
def get_public_config():
    client_id = settings.PAYPAL_CLIENT_ID if settings.is_paypal_configured else "sb"
    return {
        "paypal_client_id": client_id,
        "currency": "USD",
        "llm_provider": settings.LLM_PROVIDER,
        "is_paypal_configured": settings.is_paypal_configured,
        "require_deal_lock": settings.REQUIRE_DEAL_LOCK,
    }


@router.get(
    "/merchant/telemetry",
    status_code=status.HTTP_200_OK,
    summary="Get negotiation audit events and aggregated telemetry",
)
def get_merchant_telemetry():
    return {
        "summary": telemetry_store.get_summary_metrics(),
        "events": telemetry_store.get_telemetry(),
    }


@router.post(
    "/merchant/seed-demo",
    status_code=status.HTTP_200_OK,
    summary="Reset or seed telemetry records with standard test data",
)
def seed_demo_telemetry():
    events = telemetry_store.seed_demo_events()
    return {
        "status": "success",
        "message": f"Seeded {len(events)} telemetry audit records.",
        "summary": telemetry_store.get_summary_metrics(),
        "events": events,
    }
