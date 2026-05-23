import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from agents.news_feed import PoolInfo
from agents.schemas import LPDecision, TraderDecision, validate_lp_decision, validate_trader_decision


class LLMDecisionError(ValueError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    raw_text: str


class MockLLMClient:
    def __init__(
        self,
        *,
        trader_responses: Iterable[str | dict[str, Any]] | None = None,
        lp_responses: Iterable[str | dict[str, Any]] | None = None,
        invalid_json: bool = False,
    ):
        self.trader_responses = [_as_response_text(response) for response in trader_responses or []]
        self.lp_responses = [_as_response_text(response) for response in lp_responses or []]
        self.invalid_json = invalid_json
        self._trader_index = 0
        self._lp_index = 0

    def trader_response(self, observation: dict[str, Any]) -> LLMResponse:
        if self.invalid_json:
            return LLMResponse(raw_text="{invalid json")
        if self._trader_index < len(self.trader_responses):
            response = self.trader_responses[self._trader_index]
            self._trader_index += 1
            return LLMResponse(raw_text=response)
        return LLMResponse(raw_text=json.dumps(self._default_trader_payload(observation), sort_keys=True))

    def lp_response(self, observation: dict[str, Any]) -> LLMResponse:
        if self.invalid_json:
            return LLMResponse(raw_text="{invalid json")
        if self._lp_index < len(self.lp_responses):
            response = self.lp_responses[self._lp_index]
            self._lp_index += 1
            return LLMResponse(raw_text=response)
        return LLMResponse(raw_text=json.dumps(self._default_lp_payload(observation), sort_keys=True))

    def decide_trader(self, observation: dict[str, Any]) -> TraderDecision:
        response = self.trader_response(observation)
        pools = _pools_from_observation(observation)
        return parse_trader_decision(response.raw_text, pools=pools)

    def decide_lp(self, observation: dict[str, Any]) -> LPDecision:
        response = self.lp_response(observation)
        pools = _pools_from_observation(observation)
        return parse_lp_decision(response.raw_text, pools=pools)

    def _default_trader_payload(self, observation: dict[str, Any]) -> dict[str, Any]:
        pool = _matching_pool(observation)
        if pool is None:
            return {
                "action": "HOLD",
                "reason": "Mock client found no relevant market in the observation.",
            }

        return {
            "action": "SWAP",
            "pool_id": pool.id,
            "token_in": pool.quote_symbol,
            "amount_in": int(observation.get("default_amount_in", 10**18)),
            "max_slippage_bps": int(observation.get("default_max_slippage_bps", 100)),
            "deadline_seconds": int(observation.get("default_deadline_seconds", 300)),
            "reason": f"Mock client matched the news to {pool.base_symbol}.",
        }

    def _default_lp_payload(self, observation: dict[str, Any]) -> dict[str, Any]:
        pools = _pools_from_observation(observation)
        if not pools:
            return {
                "action": "HOLD",
                "reason": "Mock client found no configured pools.",
            }

        action = observation.get("mock_lp_action", "ADD_LIQUIDITY")
        pool = pools[0]
        if action == "REMOVE_LIQUIDITY":
            return {
                "action": "REMOVE_LIQUIDITY",
                "pool_id": pool.id,
                "lp_shares": int(observation.get("default_lp_shares", 10**18)),
                "reason": "Mock client removing liquidity from the first configured pool.",
            }
        if action == "COLLECT_FEES":
            return {
                "action": "COLLECT_FEES",
                "pool_id": pool.id,
                "lp_shares": int(observation.get("default_lp_shares", 10**18)),
                "reason": "Mock client collecting fees from the first configured pool.",
            }
        if action == "HOLD":
            return {
                "action": "HOLD",
                "reason": "Mock client was configured to hold.",
            }

        return {
            "action": "ADD_LIQUIDITY",
            "pool_id": pool.id,
            "amount_a": int(observation.get("default_amount_a", 10**18)),
            "amount_b": int(observation.get("default_amount_b", 10**18)),
            "min_lp_shares": int(observation.get("default_min_lp_shares", 0)),
            "reason": "Mock client adding liquidity to the first configured pool.",
        }


def parse_trader_decision(raw_text: str, *, pools: list[PoolInfo] | None = None) -> TraderDecision:
    payload = _parse_json_object(raw_text)
    try:
        decision = TraderDecision.model_validate(payload)
        if pools is not None:
            return validate_trader_decision(decision, pools)
        return decision
    except (ValidationError, ValueError) as exc:
        raise LLMDecisionError(f"invalid trader decision: {exc}") from exc


def parse_lp_decision(raw_text: str, *, pools: list[PoolInfo] | None = None) -> LPDecision:
    payload = _parse_json_object(raw_text)
    try:
        decision = LPDecision.model_validate(payload)
        if pools is not None:
            return validate_lp_decision(decision, pools)
        return decision
    except (ValidationError, ValueError) as exc:
        raise LLMDecisionError(f"invalid LP decision: {exc}") from exc


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LLMDecisionError(f"LLM response is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise LLMDecisionError("LLM response must be a JSON object")
    return payload


def _as_response_text(response: str | dict[str, Any]) -> str:
    if isinstance(response, str):
        return response
    return json.dumps(response, sort_keys=True)


def _pools_from_observation(observation: dict[str, Any]) -> list[PoolInfo]:
    pools = observation.get("pools", [])
    return [pool if isinstance(pool, PoolInfo) else PoolInfo.model_validate(pool) for pool in pools]


def _matching_pool(observation: dict[str, Any]) -> PoolInfo | None:
    pools = _pools_from_observation(observation)
    if not pools:
        return None

    text = _news_text(observation).lower()
    for pool in pools:
        if pool.base_symbol.lower() in text:
            return pool

    for pool in pools:
        keywords = SECTOR_KEYWORDS.get(pool.base_symbol, ())
        if any(keyword in text for keyword in keywords):
            return pool

    return None


def _news_text(observation: dict[str, Any]) -> str:
    news = observation.get("news", {})
    if isinstance(news, str):
        return news
    if isinstance(news, dict):
        return f"{news.get('headline', '')} {news.get('body', '')}"
    headline = getattr(news, "headline", "")
    body = getattr(news, "body", "")
    return f"{headline} {body}"


SECTOR_KEYWORDS = {
    "TECH": (
        "cloud",
        "chip",
        "cyber",
        "data center",
        "database",
        "processor",
        "server",
        "software",
    ),
    "FIN": (
        "bank",
        "bond",
        "brokerage",
        "credit",
        "lender",
        "loan",
        "payment",
        "settlement",
    ),
    "HLTH": ("drug", "hospital", "medical", "patient", "pharma"),
    "CSMR": ("consumer", "grocery", "retail", "travel"),
    "MLTRY": ("defense", "military"),
    "INDS": ("factory", "industrial", "logistics", "warehouse"),
    "ENRG": ("energy", "gas", "grid", "oil", "power", "utility"),
    "MATL": ("material", "metal", "mining", "wafer"),
    "COMM": ("advertising", "media", "streaming", "telecom", "wireless"),
    "REIT": ("apartment", "lease", "office", "property", "real estate", "warehouse"),
}
