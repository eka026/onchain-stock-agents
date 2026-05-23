import os
from dataclasses import dataclass

from dotenv import load_dotenv

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
    token_a: str
    token_b: str
    lp_token: str
    policy: str
    pool: str
    vault: str
    traders: list[TraderConfig]
    lps: list[LPConfig]
    google_api_key: str | None
    groq_api_key: str | None
    openai_api_key: str | None


def load() -> Config:
    trader_keys = _csv("TRADER_PRIVATE_KEYS")
    trader_models = _csv("TRADER_MODELS")
    lp_keys = _csv("LP_PRIVATE_KEYS")
    lp_models = _csv("LP_MODELS")

    if len(trader_keys) != len(trader_models):
        raise RuntimeError(
            f"TRADER_PRIVATE_KEYS has {len(trader_keys)} entries but TRADER_MODELS has {len(trader_models)}"
        )
    if len(lp_keys) != len(lp_models):
        raise RuntimeError(
            f"LP_PRIVATE_KEYS has {len(lp_keys)} entries but LP_MODELS has {len(lp_models)}"
        )

    return Config(
        rpc_url=_require("SEPOLIA_RPC_URL"),
        token_a=_require("TOKEN_A_ADDRESS"),
        token_b=_require("TOKEN_B_ADDRESS"),
        lp_token=_require("LP_TOKEN_ADDRESS"),
        policy=_require("POLICY_ADDRESS"),
        pool=_require("POOL_ADDRESS"),
        vault=_require("VAULT_ADDRESS"),
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


def _csv(key: str) -> list[str]:
    return [value.strip() for value in _require(key).split(",") if value.strip()]
