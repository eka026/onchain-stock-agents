import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class TraderConfig:
    private_key: str
    model: str


@dataclass(frozen=True)
class Config:
    rpc_url: str
    payment_token: str
    stock_token: str
    policy: str
    exchange: str
    vault: str
    firm_private_key: str
    traders: list[TraderConfig]
    google_api_key: str | None
    groq_api_key: str | None
    openai_api_key: str | None


def load() -> Config:
    keys = [k.strip() for k in _require("TRADER_PRIVATE_KEYS").split(",")]
    models = [m.strip() for m in _require("TRADER_MODELS").split(",")]

    if len(keys) != len(models):
        raise RuntimeError(
            f"TRADER_PRIVATE_KEYS has {len(keys)} entries but TRADER_MODELS has {len(models)}"
        )

    return Config(
        rpc_url=_require("SEPOLIA_RPC_URL"),
        payment_token=_require("PAYMENT_TOKEN_ADDRESS"),
        stock_token=_require("STOCK_TOKEN_ADDRESS"),
        policy=_require("POLICY_ADDRESS"),
        exchange=_require("EXCHANGE_ADDRESS"),
        vault=_require("VAULT_ADDRESS"),
        firm_private_key=_require("FIRM_PRIVATE_KEY"),
        traders=[TraderConfig(private_key=k, model=m) for k, m in zip(keys, models)],
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        groq_api_key=os.environ.get("GROQ_API_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value
