"""
Thread-safe in-memory session repository for AmpelBot.
Caches conversation history with an upper bound on turns and tracks locked deal states.
"""

import threading
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from ..models.schemas import (
    ChatMessage,
    ChatSessionResponse,
    NegotiationLLMOutput,
)
from ..models.inventory import get_internal_product


class SessionStore:
    def __init__(self, max_turns: int = 10):
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.max_turns = max_turns

    def get_or_create_session(self, session_id: str, sku: str) -> Dict[str, Any]:
        with self._lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            if session_id not in self._sessions:
                self._sessions[session_id] = {
                    "session_id": session_id,
                    "sku": sku.strip().upper(),
                    "history": [],
                    "traffic_light": "YELLOW",
                    "deal_locked": False,
                    "agreed_price": None,
                    "deal_token": None,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
            session = self._sessions[session_id]
            if not session.get("sku") and sku:
                session["sku"] = sku.strip().upper()
            return session

    def get_session(self, session_id: str) -> Optional[ChatSessionResponse]:
        with self._lock:
            raw = self._sessions.get(session_id)
            if not raw:
                return None

            sku = raw.get("sku")
            product = get_internal_product(sku) if sku else None

            return ChatSessionResponse(
                session_id=raw["session_id"],
                sku=sku,
                product_name=product.name if product else None,
                retail_price=product.retail_price if product else None,
                history=[ChatMessage(**m) for m in raw.get("history", [])],
                traffic_light=raw.get("traffic_light", "YELLOW"),
                deal_locked=raw.get("deal_locked", False),
                agreed_price=raw.get("agreed_price"),
                deal_token=raw.get("deal_token"),
                created_at=raw.get("created_at", ""),
                updated_at=raw.get("updated_at", ""),
            )

    def record_turn(
        self,
        session_id: str,
        user_text: str,
        llm_output: NegotiationLLMOutput,
        deal_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError(f"Session '{session_id}' does not exist.")

            now_iso = datetime.now(timezone.utc).isoformat()
            session["updated_at"] = now_iso

            session["history"].append({
                "role": "user",
                "content": user_text,
                "traffic_light": None,
                "counter_offer_price": None,
                "agreed_price": None,
                "reasoning_summary": None,
                "timestamp": now_iso,
            })

            session["history"].append({
                "role": "assistant",
                "content": llm_output.reply_message,
                "traffic_light": llm_output.traffic_light,
                "counter_offer_price": llm_output.counter_offer_price,
                "agreed_price": llm_output.agreed_price,
                "reasoning_summary": llm_output.reasoning_summary,
                "timestamp": now_iso,
            })

            session["traffic_light"] = llm_output.traffic_light

            if llm_output.traffic_light == "GREEN" and llm_output.agreed_price is not None:
                session["deal_locked"] = True
                session["agreed_price"] = llm_output.agreed_price
                if deal_token:
                    session["deal_token"] = deal_token

            # Bound history size to max_turns * 2 messages to prevent prompt token bloat
            max_messages = self.max_turns * 2
            if len(session["history"]) > max_messages:
                session["history"] = session["history"][-max_messages:]

            return session

    def clear(self):
        with self._lock:
            self._sessions.clear()


session_store = SessionStore(max_turns=10)
