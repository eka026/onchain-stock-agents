from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from agents.news_feed import PoolInfo


class TraderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["SWAP", "HOLD"]
    pool_id: str | None = None
    token_in: str | None = None
    amount_in: int | None = None
    reason: str

    @model_validator(mode="after")
    def validate_action_fields(self) -> "TraderDecision":
        if self.action == "SWAP" and (self.amount_in is None or self.amount_in <= 0):
            raise ValueError("SWAP amount_in must be positive")
        return self


def validate_trader_decision(decision: TraderDecision, pools: list[PoolInfo]) -> TraderDecision:
    if decision.action == "HOLD":
        return decision

    pool = next((candidate for candidate in pools if candidate.id == decision.pool_id), None)
    if pool is None:
        raise ValueError(f"unknown pool_id: {decision.pool_id}")

    valid_symbols = pool.symbols()
    if decision.token_in not in valid_symbols:
        expected = ", ".join(sorted(valid_symbols))
        raise ValueError(f"token_in must be one of {expected}")

    return decision

