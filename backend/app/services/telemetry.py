"""
Merchant audit and negotiation telemetry service for AmpelBot.
Collects transaction metrics, margin defense performance, and firewall intervention events.
"""

import threading
import uuid
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from ..models.inventory import get_internal_product, get_bundle_products
from ..models.schemas import NegotiationLLMOutput


class TelemetryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._events = self._generate_seed_events()

    def _generate_seed_events(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "AUDIT-101",
                "timestamp": "2026-10-26T21:40:12Z",
                "session_id": "demo-session-alpha",
                "sku": "AMP-01",
                "product_name": "Custom CNC 75% Aluminum Keyboard",
                "retail_price": 180.00,
                "buyer_offer": 155.00,
                "final_price": 155.00,
                "traffic_light": "GREEN",
                "discount_pct": 13.89,
                "margin_protected": "Floor: $145.00 (+$10.00 retained)",
                "reasoning_summary": "Concession approved: student budget with immediate checkout commitment.",
                "firewall_triggered": False,
                "deal_token_issued": True,
            },
            {
                "id": "AUDIT-102",
                "timestamp": "2026-10-26T21:48:33Z",
                "session_id": "demo-session-beta",
                "sku": "AMP-01",
                "product_name": "Custom CNC 75% Aluminum Keyboard",
                "retail_price": 180.00,
                "buyer_offer": 1.00,
                "final_price": 162.00,
                "traffic_light": "RED",
                "discount_pct": 0.0,
                "margin_protected": "Floor: $145.00 (Breach neutralized)",
                "reasoning_summary": "[SECURITY FIREWALL INTERCEPTION] Attempted price $1.00 breached floor $145.00. Overridden to RED.",
                "firewall_triggered": True,
                "deal_token_issued": False,
            },
            {
                "id": "AUDIT-103",
                "timestamp": "2026-10-26T21:55:04Z",
                "session_id": "demo-session-gamma",
                "sku": "AMP-02",
                "product_name": "Vintage 2008 Football Kit",
                "retail_price": 95.00,
                "buyer_offer": 78.00,
                "final_price": 82.00,
                "traffic_light": "YELLOW",
                "discount_pct": 13.68,
                "margin_protected": "Floor: $72.00 (Negotiation active)",
                "reasoning_summary": "Counter-offered at $82.00 to preserve target margin threshold.",
                "firewall_triggered": False,
                "deal_token_issued": False,
            },
            {
                "id": "AUDIT-104",
                "timestamp": "2026-10-26T22:02:44Z",
                "session_id": "demo-session-delta",
                "sku": "AMP-03",
                "product_name": "DevSecOps Lab Automation Bundle",
                "retail_price": 49.00,
                "buyer_offer": 35.00,
                "final_price": 35.00,
                "traffic_light": "GREEN",
                "discount_pct": 28.57,
                "margin_protected": "Floor: $25.00 (+$10.00 retained)",
                "reasoning_summary": "Target margin threshold satisfied. Checkout authorized.",
                "firewall_triggered": False,
                "deal_token_issued": True,
            },
            {
                "id": "AUDIT-105",
                "timestamp": "2026-10-26T22:15:19Z",
                "session_id": "demo-session-epsilon",
                "sku": "AMP-02",
                "product_name": "Vintage 2008 Football Kit",
                "retail_price": 95.00,
                "buyer_offer": 40.00,
                "final_price": 82.00,
                "traffic_light": "RED",
                "discount_pct": 0.0,
                "margin_protected": "Floor: $72.00 (Sub-floor rejected)",
                "reasoning_summary": "[GUARDRAIL] Lowball offer of $40.00 is strictly below seller cost floor $72.00. Rejection returned with target price.",
                "firewall_triggered": True,
                "deal_token_issued": False,
            },
        ]

    def seed_demo_events(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._events = self._generate_seed_events()
            return list(self._events)

    def record_turn(
        self,
        session_id: str,
        sku: str,
        user_message: str,
        decision: NegotiationLLMOutput,
        deal_token: Optional[str] = None,
        bundled_skus: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        bundle = bundled_skus or decision.bundled_skus
        if bundle and len(bundle) > 1:
            try:
                products = get_bundle_products(bundle)
                product_name = " + ".join(p.name[:18] for p in products)
                retail = round(sum(p.retail_price for p in products), 2)
                floor = round(sum(p.floor_price for p in products), 2)
                display_sku = " + ".join(sorted(bundle)) + " [BUNDLE]"
            except Exception:
                product = get_internal_product(sku)
                product_name = product.name if product else sku
                retail = product.retail_price if product else 0.0
                floor = product.floor_price if product else 0.0
                display_sku = sku
        else:
            product = get_internal_product(sku)
            product_name = product.name if product else sku
            retail = product.retail_price if product else 0.0
            floor = product.floor_price if product else 0.0
            display_sku = sku

        matches = re.findall(r"\$?\s*([0-9]+(?:\.[0-9]{1,2})?)", user_message)
        buyer_offer = float(matches[-1]) if matches else None

        final_price = decision.agreed_price if decision.traffic_light == "GREEN" else decision.counter_offer_price
        discount_pct = 0.0
        if decision.traffic_light == "GREEN" and decision.agreed_price and retail > 0:
            discount_pct = round(((retail - decision.agreed_price) / retail) * 100.0, 2)

        firewall_triggered = (
            "[SECURITY" in decision.reasoning_summary
            or "[GUARDRAIL" in decision.reasoning_summary
        )

        margin_desc = f"Floor: ${floor:.2f}"
        if decision.traffic_light == "GREEN" and decision.agreed_price:
            buffer = decision.agreed_price - floor
            margin_desc = f"Floor: ${floor:.2f} (+${buffer:.2f} preserved)"
        elif firewall_triggered:
            margin_desc = f"Floor: ${floor:.2f} (Breach neutralized!)"

        event = {
            "id": f"AUDIT-{uuid.uuid4().hex[:6].upper()}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "sku": display_sku,
            "product_name": product_name[:40],
            "retail_price": retail,
            "buyer_offer": buyer_offer,
            "final_price": final_price,
            "traffic_light": decision.traffic_light,
            "discount_pct": discount_pct,
            "margin_protected": margin_desc,
            "reasoning_summary": decision.reasoning_summary,
            "firewall_triggered": firewall_triggered,
            "deal_token_issued": bool(deal_token),
            "bundled_skus": bundle if bundle and len(bundle) > 1 else None,
        }

        with self._lock:
            self._events.insert(0, event)
            if len(self._events) > 100:
                self._events.pop()

        return event

    def get_telemetry(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def get_summary_metrics(self) -> Dict[str, Any]:
        with self._lock:
            total_turns = len(self._events)
            unique_sessions = len(set(e.get("session_id", "s") for e in self._events)) if self._events else 0
            deals_closed = sum(1 for e in self._events if e["traffic_light"] == "GREEN")
            attacks_blocked = sum(1 for e in self._events if e.get("firewall_triggered"))
            green_events = [e for e in self._events if e["traffic_light"] == "GREEN" and e.get("final_price")]
            revenue_unlocked = sum(e["final_price"] for e in green_events)
            avg_discount = (
                round(sum(e["discount_pct"] for e in green_events) / len(green_events), 2)
                if green_events else 0.0
            )

            margin_retained_dollars = []
            margin_retained_pcts = []
            for e in green_events:
                if e.get("bundled_skus"):
                    try:
                        prods = get_bundle_products(e["bundled_skus"])
                        floor = sum(p.floor_price for p in prods)
                        retail = sum(p.retail_price for p in prods)
                    except Exception:
                        floor = 0.0
                        retail = e.get("retail_price", 0.0)
                else:
                    prod = get_internal_product(e.get("sku", ""))
                    floor = prod.floor_price if prod else 0.0
                    retail = prod.retail_price if prod else (e.get("retail_price") or floor)
                price = e.get("final_price", floor)
                dollar_buffer = max(0.0, price - floor)
                margin_retained_dollars.append(dollar_buffer)
                if retail > floor:
                    margin_retained_pcts.append((dollar_buffer / (retail - floor)) * 100.0)

            avg_margin_dollars = (
                round(sum(margin_retained_dollars) / len(margin_retained_dollars), 2)
                if margin_retained_dollars else 0.0
            )
            avg_margin_pct = (
                round(sum(margin_retained_pcts) / len(margin_retained_pcts), 1)
                if margin_retained_pcts else 0.0
            )
            conversion_rate = (
                round((deals_closed / unique_sessions) * 100.0, 1)
                if unique_sessions else 0.0
            )

            return {
                "total_negotiations": total_turns,
                "deals_closed": deals_closed,
                "attacks_blocked": attacks_blocked,
                "revenue_unlocked": round(revenue_unlocked, 2),
                "avg_discount_percent": avg_discount,
                "gmv_locked_captured": round(revenue_unlocked, 2),
                "avg_margin_retained_dollars": avg_margin_dollars,
                "avg_margin_retained_pct": avg_margin_pct,
                "margin_retained_summary": f"+${avg_margin_dollars:.2f} ({avg_margin_pct:.1f}% profit retained)",
                "total_sessions": unique_sessions,
                "conversion_funnel": f"{deals_closed} / {unique_sessions} Sessions ({conversion_rate:.1f}%)",
                "conversion_rate_pct": conversion_rate,
                "security_interventions_count": attacks_blocked,
            }


telemetry_store = TelemetryStore()
