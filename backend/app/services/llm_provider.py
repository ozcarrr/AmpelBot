"""
Model-agnostic LLM provider adapters for AmpelBot.
Supports Google Gemini, OpenAI-compatible REST endpoints, and a deterministic fallback engine.
"""

import re
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import httpx

from ..config import settings
from ..models.schemas import NegotiationLLMOutput, TrafficLight

logger = logging.getLogger("ampelbot.llm")


def _clean_json_markdown(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate_negotiation_turn(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_message: str,
    ) -> NegotiationLLMOutput:
        pass


class DeterministicMockProvider(BaseLLMProvider):
    """Deterministic mathematical rule engine used for testing and offline fallback."""

    def _extract_prices_from_prompt(self, system_prompt: str) -> Dict[str, float]:
        prices = {"retail": 180.0, "target": 162.0, "floor": 145.0}

        retail_match = re.search(r"Retail Price:\s*\$([0-9]+(?:\.[0-9]+)?)", system_prompt)
        if retail_match:
            prices["retail"] = float(retail_match.group(1))

        target_match = re.search(r"Target Price:\s*\$([0-9]+(?:\.[0-9]+)?)", system_prompt)
        if target_match:
            prices["target"] = float(target_match.group(1))

        floor_match = re.search(r"Floor Price:\s*\$([0-9]+(?:\.[0-9]+)?)", system_prompt)
        if floor_match:
            prices["floor"] = float(floor_match.group(1))

        return prices

    def _extract_user_offer(self, user_message: str) -> Optional[float]:
        matches = re.findall(r"\$?\s*([0-9]+(?:\.[0-9]{1,2})?)\s*(?:usd|dollars|\$)?", user_message.lower())
        if not matches:
            return None

        for match in reversed(matches):
            try:
                val = float(match)
                if val > 0:
                    return val
            except ValueError:
                continue
        return None

    async def generate_negotiation_turn(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_message: str,
    ) -> NegotiationLLMOutput:
        thresholds = self._extract_prices_from_prompt(system_prompt)
        retail = thresholds["retail"]
        target = thresholds["target"]
        floor = thresholds["floor"]
        offer = self._extract_user_offer(user_message)

        # Cross-sell bundling detection
        bundle_signals = ["bundle", "amp-03", "cross-sell", "cross sell", "package", "combo"]
        is_bundle_requested = any(s in user_message.lower() for s in bundle_signals)
        last_turn_was_bundle = any(
            "amp-03" in m.get("content", "").lower() or "bundle" in m.get("content", "").lower()
            for m in conversation_history[-2:]
        ) if conversation_history else False

        if is_bundle_requested or (last_turn_was_bundle and offer is not None and offer >= 170.0):
            bundled_skus = ["AMP-01", "AMP-03"]
            composite_retail = 229.00
            composite_floor = 170.00
            bundle_deal_price = 175.00

            if offer is None:
                return NegotiationLLMOutput(
                    reply_message=f"Cross-sell bundle available: AMP-01 with AMP-03 for ${bundle_deal_price:.2f} total (saves $54.00 off ${composite_retail:.2f} retail).",
                    traffic_light="YELLOW",
                    counter_offer_price=bundle_deal_price,
                    agreed_price=None,
                    bundled_skus=bundled_skus,
                    reasoning_summary="Proposed high-AOV cross-sell bundle (AMP-01 + AMP-03).",
                )

            if offer >= composite_floor:
                return NegotiationLLMOutput(
                    reply_message=f"Cross-sell bundle agreed: AMP-01 and AMP-03 for ${offer:.2f}. Checkout authorized.",
                    traffic_light="GREEN",
                    counter_offer_price=None,
                    agreed_price=offer,
                    bundled_skus=bundled_skus,
                    reasoning_summary=f"Accepted multi-SKU cross-sell bundle at ${offer:.2f} (above composite floor ${composite_floor:.2f}).",
                )

            return NegotiationLLMOutput(
                reply_message=f"Bundle offer ${offer:.2f} is below composite floor. Best bundle offer is ${bundle_deal_price:.2f}.",
                traffic_light="RED",
                counter_offer_price=bundle_deal_price,
                agreed_price=None,
                bundled_skus=bundled_skus,
                reasoning_summary=f"Bundle offer ${offer:.2f} is below composite floor ${composite_floor:.2f}. Rejected.",
            )

        if offer is None:
            return NegotiationLLMOutput(
                reply_message=f"Standard retail price is ${retail:.2f}. Submit an offer to begin negotiation.",
                traffic_light="YELLOW",
                counter_offer_price=target,
                agreed_price=None,
                reasoning_summary="No price offer detected. Prompting buyer for initial numerical proposal.",
            )

        if offer >= retail:
            return NegotiationLLMOutput(
                reply_message=f"Offer of ${offer:.2f} satisfies standard retail price. Checkout authorized.",
                traffic_light="GREEN",
                counter_offer_price=None,
                agreed_price=offer,
                reasoning_summary=f"Offer of ${offer:.2f} meets or exceeds standard retail list price.",
            )

        if offer >= target:
            return NegotiationLLMOutput(
                reply_message=f"Offer of ${offer:.2f} meets target margin threshold. Checkout authorized.",
                traffic_light="GREEN",
                counter_offer_price=None,
                agreed_price=offer,
                reasoning_summary=f"Offer of ${offer:.2f} satisfies target margin threshold (${target:.2f}).",
            )

        if offer < floor:
            return NegotiationLLMOutput(
                reply_message=(
                    f"Offer ${offer:.2f} is below our cost. "
                    f"The best offer I can make is ${target:.2f}."
                ),
                traffic_light="RED",
                counter_offer_price=target,
                agreed_price=None,
                reasoning_summary=f"Offer of ${offer:.2f} is below hard profitability floor (${floor:.2f}). Rejected.",
            )

        concession_signals = ["student", "budget", "immediately", "right now", "collector", "today", "cash", "deal"]
        has_concession = any(k in user_message.lower() for k in concession_signals)
        user_turns_in_history = sum(1 for m in conversation_history if m.get("role") == "user")
        is_repeat_offer = user_turns_in_history >= 1 or has_concession or offer >= (floor + (target - floor) * 0.70)

        if is_repeat_offer:
            return NegotiationLLMOutput(
                reply_message=f"Concession terms accepted. Agreed price: ${offer:.2f}. Checkout authorized.",
                traffic_light="GREEN",
                counter_offer_price=None,
                agreed_price=offer,
                reasoning_summary=f"Concession granted at ${offer:.2f} after active bargaining (above floor ${floor:.2f}).",
            )

        counter = round((offer + target) / 2.0, 2)
        return NegotiationLLMOutput(
            reply_message=f"Offer ${offer:.2f} is below target threshold. Counter-offer: ${counter:.2f}.",
            traffic_light="YELLOW",
            counter_offer_price=counter,
            agreed_price=None,
            reasoning_summary=f"Bargaining in progress: countered ${offer:.2f} with compromise at ${counter:.2f}.",
        )


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API client using structured JSON generation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 20.0,
        fallback_provider: Optional[BaseLLMProvider] = None,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.timeout = timeout_seconds
        self.fallback = fallback_provider or DeterministicMockProvider()

    async def generate_negotiation_turn(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_message: str,
    ) -> NegotiationLLMOutput:
        if not self.api_key or "your_" in self.api_key:
            return await self.fallback.generate_negotiation_turn(system_prompt, conversation_history, user_message)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        contents = []
        for turn in conversation_history:
            role = "model" if turn.get("role") in ("assistant", "model") else "user"
            contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        request_body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.3,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=request_body)

            if response.status_code != 200:
                logger.error("Gemini API error HTTP %s: %s", response.status_code, response.text)
                return await self.fallback.generate_negotiation_turn(system_prompt, conversation_history, user_message)

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return await self.fallback.generate_negotiation_turn(system_prompt, conversation_history, user_message)

            text_output = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            cleaned_json = _clean_json_markdown(text_output)
            parsed_dict = json.loads(cleaned_json)
            return NegotiationLLMOutput(**parsed_dict)

        except Exception as e:
            logger.warning("Gemini invocation failed (%s). Executing mock fallback.", str(e))
            return await self.fallback.generate_negotiation_turn(system_prompt, conversation_history, user_message)


class OpenAICompatProvider(BaseLLMProvider):
    """OpenAI-compatible REST API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 20.0,
        fallback_provider: Optional[BaseLLMProvider] = None,
    ):
        self.api_key = api_key or settings.OPENAI_COMPAT_API_KEY
        self.base_url = (base_url or settings.OPENAI_COMPAT_BASE_URL).rstrip("/")
        self.model = model or settings.OPENAI_COMPAT_MODEL
        self.timeout = timeout_seconds
        self.fallback = fallback_provider or DeterministicMockProvider()

    async def generate_negotiation_turn(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_message: str,
    ) -> NegotiationLLMOutput:
        if not self.api_key or "your_" in self.api_key:
            return await self.fallback.generate_negotiation_turn(system_prompt, conversation_history, user_message)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = [{"role": "system", "content": system_prompt}]
        for turn in conversation_history:
            role = "assistant" if turn.get("role") in ("assistant", "model") else "user"
            messages.append({"role": role, "content": turn.get("content", "")})
        messages.append({"role": "user", "content": user_message})

        request_body = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=request_body)

            if response.status_code != 200:
                logger.error("OpenAI-compatible API error HTTP %s: %s", response.status_code, response.text)
                return await self.fallback.generate_negotiation_turn(system_prompt, conversation_history, user_message)

            data = response.json()
            raw_content = data["choices"][0]["message"]["content"]
            cleaned_json = _clean_json_markdown(raw_content)
            parsed_dict = json.loads(cleaned_json)
            return NegotiationLLMOutput(**parsed_dict)

        except Exception as e:
            logger.warning("OpenAI-compatible call failed (%s). Executing mock fallback.", str(e))
            return await self.fallback.generate_negotiation_turn(system_prompt, conversation_history, user_message)


def get_llm_provider(
    provider_type: Optional[str] = None,
    fallback_to_mock: bool = True,
) -> BaseLLMProvider:
    selected = (provider_type or settings.LLM_PROVIDER).strip().lower()
    fallback = DeterministicMockProvider() if fallback_to_mock else None

    if selected == "gemini":
        return GeminiProvider(fallback_provider=fallback)
    if selected in ("openai", "openai_compat", "openrouter"):
        return OpenAICompatProvider(fallback_provider=fallback)
    if selected in ("mock", "test", "deterministic"):
        return DeterministicMockProvider()

    logger.warning("Unrecognized provider '%s'. Falling back to DeterministicMockProvider.", selected)
    return DeterministicMockProvider()
