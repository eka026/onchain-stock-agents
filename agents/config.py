import os
from dataclasses import dataclass

from dotenv import load_dotenv

from agents.news_feed import NewsFeed, Scenario

load_dotenv()


@dataclass(frozen=True)
class TraderConfig:
    private_key: str
    model: str


@dataclass(frozen=True)
class LPConfig:
    private_key: str
    model: str


@dataclass(frozen=True)
class Config:
    rpc_url: str
    scenario_path: str
    scenario: Scenario
    traders: list[TraderConfig]
    lps: list[LPConfig]
    google_api_key: str | None
    groq_api_key: str | None
    openai_api_key: str | None


def load(
    *,
    require_traders: bool = True,
    require_lps: bool = True,
    scenario_path: str | None = None,
) -> Config:
    trader_keys, trader_models = _agent_pair_csv(
        "TRADER_PRIVATE_KEYS",
        "TRADER_MODELS",
        required=require_traders,
    )
    lp_keys, lp_models = _agent_pair_csv(
        "LP_PRIVATE_KEYS",
        "LP_MODELS",
        required=require_lps,
    )

    if len(trader_keys) != len(trader_models):
        raise RuntimeError(
            f"TRADER_PRIVATE_KEYS has {len(trader_keys)} entries but TRADER_MODELS has {len(trader_models)}"
        )
    if len(lp_keys) != len(lp_models):
        raise RuntimeError(
            f"LP_PRIVATE_KEYS has {len(lp_keys)} entries but LP_MODELS has {len(lp_models)}"
        )

    resolved_scenario_path = scenario_path or os.environ.get("SCENARIO_PATH", "data/scenarios/demo.json")

    return Config(
        rpc_url=_require("SEPOLIA_RPC_URL"),
        scenario_path=resolved_scenario_path,
        scenario=NewsFeed.load_scenario(resolved_scenario_path),
        traders=[TraderConfig(private_key=k, model=m) for k, m in zip(trader_keys, trader_models)],
        lps=[LPConfig(private_key=k, model=m) for k, m in zip(lp_keys, lp_models)],
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        groq_api_key=os.environ.get("GROQ_API_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value


def _csv(key: str, *, required: bool = True) -> list[str]:
    if not required and key not in os.environ:
        return []
    return [value.strip() for value in _require(key).split(",") if value.strip()]


def _agent_pair_csv(keys_env: str, models_env: str, *, required: bool) -> tuple[list[str], list[str]]:
    has_keys = keys_env in os.environ
    has_models = models_env in os.environ
    if not required and not has_keys and not has_models:
        return [], []
    if not required and has_keys != has_models:
        raise RuntimeError(f"{keys_env} and {models_env} must both be set or both be omitted")
    return _csv(keys_env), _csv(models_env)
