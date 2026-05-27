import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from agents.news_feed import PoolInfo
from agents.schemas import LPDecision, TraderDecision, validate_lp_decision, validate_trader_decision

_DEFAULT_PERSONA_PATH = Path(__file__).resolve().parent.parent / "data" / "persona.json"


def load_persona(index: int, path: str | Path = _DEFAULT_PERSONA_PATH) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    personas = data["personas"]
    return personas[index % len(personas)]["system_prompt"]


class LLMDecisionError(ValueError):
    pass


class LLMConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    raw_text: str
    model: str = "mock"
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    latency_ms: int | None = None


class LLMClient(Protocol):
    def decide_trader(self, observation: dict[str, Any]) -> TraderDecision:
        ...

    def decide_lp(self, observation: dict[str, Any]) -> LPDecision:
        ...


SYSTEM_INSTRUCTIONS = (
    "You are an off-chain AMM simulation agent. Return only one JSON object that matches the requested "
    "decision schema. Use only the exact enum values shown in the schema. Do not include markdown, "
    "comments, hidden reasoning, or extra text."
)


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

    def reset(self) -> None:
        self._trader_index = 0
        self._lp_index = 0

    def trader_response(self, observation: dict[str, Any]) -> LLMResponse:
        pools = _pools_from_observation(observation)
        return self._trader_response(observation, pools)

    def _trader_response(self, observation: dict[str, Any], pools: list[PoolInfo]) -> LLMResponse:
        if self.invalid_json:
            return LLMResponse(raw_text="{invalid json")
        if self._trader_index < len(self.trader_responses):
            response = self.trader_responses[self._trader_index]
            self._trader_index += 1
            return LLMResponse(raw_text=response)
        return LLMResponse(raw_text=json.dumps(self._default_trader_payload(observation, pools), sort_keys=True))

    def lp_response(self, observation: dict[str, Any]) -> LLMResponse:
        pools = _pools_from_observation(observation)
        return self._lp_response(observation, pools)

    def _lp_response(self, observation: dict[str, Any], pools: list[PoolInfo]) -> LLMResponse:
        if self.invalid_json:
            return LLMResponse(raw_text="{invalid json")
        if self._lp_index < len(self.lp_responses):
            response = self.lp_responses[self._lp_index]
            self._lp_index += 1
            return LLMResponse(raw_text=response)
        return LLMResponse(raw_text=json.dumps(self._default_lp_payload(observation, pools), sort_keys=True))

    def decide_trader(self, observation: dict[str, Any]) -> TraderDecision:
        pools = _pools_from_observation(observation)
        response = self._trader_response(observation, pools)
        return parse_trader_decision(response.raw_text, pools=pools)

    def decide_lp(self, observation: dict[str, Any]) -> LPDecision:
        pools = _pools_from_observation(observation)
        response = self._lp_response(observation, pools)
        return parse_lp_decision(response.raw_text, pools=pools)

    def _default_trader_payload(self, observation: dict[str, Any], pools: list[PoolInfo]) -> dict[str, Any]:
        pool = _matching_pool(observation, pools)
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

    def _default_lp_payload(self, observation: dict[str, Any], pools: list[PoolInfo]) -> dict[str, Any]:
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


class ProviderLLMClient:
    def __init__(self, *, model: str, persona_prompt: str = ""):
        self.model = model
        self.persona_prompt = persona_prompt

    def _system_message(self) -> str:
        if self.persona_prompt:
            return f"{self.persona_prompt}\n\n{SYSTEM_INSTRUCTIONS}"
        return SYSTEM_INSTRUCTIONS

    def trader_response(self, observation: dict[str, Any]) -> LLMResponse:
        return self._json_response(_build_prompt("trader", observation))

    def lp_response(self, observation: dict[str, Any]) -> LLMResponse:
        return self._json_response(_build_prompt("lp", observation))

    def decide_trader(self, observation: dict[str, Any]) -> TraderDecision:
        pools = _pools_from_observation(observation)
        return parse_trader_decision(self.trader_response(observation).raw_text, pools=pools)

    def decide_lp(self, observation: dict[str, Any]) -> LPDecision:
        pools = _pools_from_observation(observation)
        return parse_lp_decision(self.lp_response(observation).raw_text, pools=pools)

    def _json_response(self, prompt: str) -> LLMResponse:
        raise NotImplementedError


class OpenAILLMClient(ProviderLLMClient):
    def __init__(self, *, model: str, api_key: str | None, persona_prompt: str = "", client: Any | None = None):
        super().__init__(model=model, persona_prompt=persona_prompt)
        if not api_key:
            raise LLMConfigurationError("missing OPENAI_API_KEY for OpenAI model")
        self.client = client or self._create_client(api_key)

    def _json_response(self, prompt: str) -> LLMResponse:
        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.model,
            instructions=self._system_message(),
            input=prompt,
            text={"format": {"type": "json_object"}},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return LLMResponse(
            raw_text=_response_attr(response, "output_text"),
            model=self.model,
            finish_reason=_response_attr(response, "status", default=None),
            usage=_usage_dict(_response_attr(response, "usage", default=None)),
            latency_ms=latency_ms,
        )

    def _create_client(self, api_key: str) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise LLMConfigurationError("openai package is required for OpenAI models") from exc
        return OpenAI(api_key=api_key)


class GeminiLLMClient(ProviderLLMClient):
    def __init__(self, *, model: str, api_key: str | None, persona_prompt: str = "", client: Any | None = None):
        super().__init__(model=model, persona_prompt=persona_prompt)
        if not api_key:
            raise LLMConfigurationError("missing GOOGLE_API_KEY for Gemini model")
        self.client = client or self._create_client(api_key)

    def _json_response(self, prompt: str) -> LLMResponse:
        started = time.perf_counter()
        response = self.client.generate_content(
            f"{self._system_message()}\n\n{prompt}",
            generation_config={"response_mime_type": "application/json"},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return LLMResponse(
            raw_text=_response_text(response),
            model=self.model,
            finish_reason=_gemini_finish_reason(response),
            usage=_usage_dict(_response_attr(response, "usage_metadata", default=None)),
            latency_ms=latency_ms,
        )

    def _create_client(self, api_key: str) -> Any:
        try:
            import google.generativeai as genai
        except ModuleNotFoundError as exc:
            raise LLMConfigurationError("google-generativeai package is required for Gemini models") from exc
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(self.model)


class GroqLLMClient(ProviderLLMClient):
    def __init__(self, *, model: str, api_key: str | None, persona_prompt: str = "", client: Any | None = None):
        # Strip the "groq/" provider prefix if present (e.g. "groq/compound-mini" → "compound-mini")
        super().__init__(model=model.split("groq/", 1)[-1] if model.lower().startswith("groq/") else model, persona_prompt=persona_prompt)
        if not api_key:
            raise LLMConfigurationError("missing GROQ_API_KEY for Groq model")
        self.client = client or self._create_client(api_key)

    def _json_response(self, prompt: str) -> LLMResponse:
        started = time.perf_counter()
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._system_message()},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        choice = completion.choices[0]
        return LLMResponse(
            raw_text=choice.message.content,
            model=self.model,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=_usage_dict(_response_attr(completion, "usage", default=None)),
            latency_ms=latency_ms,
        )

    def _create_client(self, api_key: str) -> Any:
        try:
            from groq import Groq
        except ModuleNotFoundError as exc:
            raise LLMConfigurationError("groq package is required for Groq models") from exc
        return Groq(api_key=api_key)


class OpenRouterLLMClient(ProviderLLMClient):
    """Routes requests through OpenRouter (openai-compatible API).

    Handles any model served by OpenRouter, e.g. 'meta-llama/llama-3.3-70b-instruct:free'.
    """

    def __init__(self, *, model: str, api_key: str | None, persona_prompt: str = "", client: Any | None = None):
        super().__init__(model=model, persona_prompt=persona_prompt)
        if not api_key:
            raise LLMConfigurationError("missing OPENROUTER_API_KEY for OpenRouter model")
        self.client = client or self._create_client(api_key)

    def _json_response(self, prompt: str) -> LLMResponse:
        started = time.perf_counter()
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._system_message()},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        choice = completion.choices[0]
        return LLMResponse(
            raw_text=choice.message.content,
            model=self.model,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=_usage_dict(_response_attr(completion, "usage", default=None)),
            latency_ms=latency_ms,
        )

    def _create_client(self, api_key: str) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise LLMConfigurationError("openai package is required for OpenRouter models") from exc
        return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


class DeepSeekLLMClient(ProviderLLMClient):
    """Calls DeepSeek's OpenAI-compatible API at api.deepseek.com."""

    def __init__(self, *, model: str, api_key: str | None, persona_prompt: str = "", client: Any | None = None):
        super().__init__(model=model, persona_prompt=persona_prompt)
        if not api_key:
            raise LLMConfigurationError("missing DEEPSEEK_API_KEY for DeepSeek model")
        self.client = client or self._create_client(api_key)

    def _json_response(self, prompt: str) -> LLMResponse:
        started = time.perf_counter()
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._system_message()},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        choice = completion.choices[0]
        return LLMResponse(
            raw_text=choice.message.content,
            model=self.model,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=_usage_dict(_response_attr(completion, "usage", default=None)),
            latency_ms=latency_ms,
        )

    def _create_client(self, api_key: str) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise LLMConfigurationError("openai package is required for DeepSeek models") from exc
        return OpenAI(base_url="https://api.deepseek.com", api_key=api_key)


def create_llm_client(
    model: str,
    *,
    openai_api_key: str | None = None,
    google_api_key: str | None = None,
    groq_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    deepseek_api_key: str | None = None,
    persona_prompt: str = "",
) -> LLMClient:
    normalized = model.lower()
    if normalized == "mock":
        return MockLLMClient()
    # Explicit groq/ prefix → Groq API (strips prefix internally)
    if normalized.startswith("groq/"):
        return GroqLLMClient(model=model, api_key=groq_api_key, persona_prompt=persona_prompt)
    # Any slash-qualified model name (e.g. meta-llama/..., deepseek/...) → OpenRouter
    if "/" in normalized:
        return OpenRouterLLMClient(model=model, api_key=openrouter_api_key, persona_prompt=persona_prompt)
    # deepseek-* without slash → DeepSeek direct API
    if normalized.startswith("deepseek"):
        return DeepSeekLLMClient(model=model, api_key=deepseek_api_key, persona_prompt=persona_prompt)
    if _is_openai_model(normalized):
        return OpenAILLMClient(model=model, api_key=openai_api_key, persona_prompt=persona_prompt)
    if "gemini" in normalized:
        return GeminiLLMClient(model=model, api_key=google_api_key, persona_prompt=persona_prompt)
    if _is_groq_model(normalized):
        return GroqLLMClient(model=model, api_key=groq_api_key, persona_prompt=persona_prompt)
    raise LLMConfigurationError(f"unsupported LLM model: {model}")


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
    return [pool if isinstance(pool, PoolInfo) else PoolInfo.model_validate(_pool_info_fields(pool)) for pool in pools]


def _pool_info_fields(pool: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pool["id"],
        "base_symbol": pool["base_symbol"],
        "quote_symbol": pool["quote_symbol"],
        "pool_address": pool["pool_address"],
        "lp_token_address": pool["lp_token_address"],
        "vault_address": pool["vault_address"],
    }


def _build_prompt(agent_type: str, observation: dict[str, Any]) -> str:
    if agent_type == "trader":
        schema = {
            "action": ["SWAP", "HOLD"],
            "pool_id": "pool id for SWAP",
            "token_in": "input token symbol for SWAP",
            "amount_in": "positive integer for SWAP",
            "max_slippage_bps": "optional integer",
            "deadline_seconds": "optional positive integer",
            "reason": "one short sentence, no hidden reasoning",
        }
        rules = "Do not return BUY or SELL. To buy or sell, use SWAP with token_in set to the token being sold."
    elif agent_type == "lp":
        schema = {
            "action": ["ADD_LIQUIDITY", "REMOVE_LIQUIDITY", "COLLECT_FEES", "HOLD"],
            "pool_id": "pool id for non-HOLD actions",
            "amount_a": "positive integer for ADD_LIQUIDITY",
            "amount_b": "positive integer for ADD_LIQUIDITY",
            "lp_shares": "positive integer for REMOVE_LIQUIDITY or COLLECT_FEES",
            "min_lp_shares": "optional integer for ADD_LIQUIDITY",
            "reason": "one short sentence, no hidden reasoning",
        }
        rules = "Use only the action enum values. Do not invent deposit, withdraw, or claim action names."
    else:
        raise ValueError(f"unsupported agent_type: {agent_type}")

    news_item = observation.get("news") or {}
    if isinstance(news_item, dict):
        news_text = f"{news_item.get('headline', '')} {news_item.get('body', '')}".strip()
    else:
        news_text = str(news_item)

    return json.dumps(
        {
            "portfolio": observation.get("balances", {}),
            "per_token_history": observation.get("per_token_history", {}),
            "news": news_text,
            "prompt": (
                f"You are acting as a {agent_type} agent on an on-chain AMM. "
                f"Given your portfolio, token price history, and the latest news, "
                f"return exactly one JSON decision matching the schema below."
            ),
            "rules": rules,
            "schema": schema,
            "pools": observation.get("pools", []),
            "policy": observation.get("policy", {}),
        },
        default=_json_default,
        sort_keys=True,
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _is_openai_model(normalized_model: str) -> bool:
    return normalized_model.startswith(("gpt-", "o1", "o2", "o3", "o4", "o5", "chatgpt-"))


def _is_groq_model(normalized_model: str) -> bool:
    return any(prefix in normalized_model for prefix in ("llama", "groq", "mixtral", "gemma"))


def _response_attr(value: Any, name: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _response_text(response: Any) -> str:
    text = _response_attr(response, "text", default=None)
    if text is not None:
        return text
    candidates = _response_attr(response, "candidates", default=[])
    if candidates:
        content = _response_attr(candidates[0], "content", default=None)
        parts = _response_attr(content, "parts", default=[])
        if parts:
            return _response_attr(parts[0], "text")
    return ""


def _gemini_finish_reason(response: Any) -> str | None:
    candidates = _response_attr(response, "candidates", default=[])
    if not candidates:
        return None
    reason = _response_attr(candidates[0], "finish_reason", default=None)
    return str(reason) if reason is not None else None


def _usage_dict(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return {key: value for key, value in usage.items() if isinstance(value, int)}

    result = {}
    for source, target in (
        ("prompt_tokens", "prompt_tokens"),
        ("completion_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("total_token_count", "total_tokens"),
        ("prompt_token_count", "prompt_tokens"),
        ("candidates_token_count", "completion_tokens"),
    ):
        value = getattr(usage, source, None)
        if isinstance(value, int):
            result[target] = value
    return result or None


def _matching_pool(observation: dict[str, Any], pools: list[PoolInfo]) -> PoolInfo | None:
    if not pools:
        return None

    text = _news_text(observation).lower()
    tokens = set(re.findall(r"\b[a-z0-9]+\b", text))
    for pool in pools:
        if pool.base_symbol.lower() in tokens:
            return pool

    for pool in pools:
        keywords = SECTOR_KEYWORDS.get(pool.base_symbol, ())
        if any(_contains_keyword(text, keyword) for keyword in keywords):
            return pool

    return None


def _contains_keyword(text: str, keyword: str) -> bool:
    return re.search(r"\b" + re.escape(keyword.lower()) + r"\b", text) is not None


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
    "INDS": ("factory", "industrial", "logistics"),
    "ENRG": ("energy", "gas", "grid", "oil", "power", "utility"),
    "MATL": ("material", "metal", "mining", "wafer"),
    "COMM": ("advertising", "media", "streaming", "telecom", "wireless"),
    "REIT": ("apartment", "lease", "office", "property", "real estate", "warehouse"),
}
