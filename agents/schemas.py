from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.news_feed import PoolInfo


class TraderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["SWAP", "HOLD"]
    pool_id: str | None = None
    token_in: str | None = None
    amount_in: int | None = None
    max_slippage_bps: int | None = Field(default=None, ge=0, le=10_000)
    deadline_seconds: int | None = Field(default=None, gt=0)
    reason: str

    @model_validator(mode="after")
    def validate_action_fields(self) -> "TraderDecision":
        if self.action == "SWAP":
            if not self.pool_id:
                raise ValueError("SWAP pool_id is required")
            if not self.token_in:
                raise ValueError("SWAP token_in is required")
            if self.amount_in is None or self.amount_in <= 0:
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


class LPDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["ADD_LIQUIDITY", "REMOVE_LIQUIDITY", "COLLECT_FEES", "HOLD"]
    pool_id: str | None = None
    amount_a: int | None = None
    amount_b: int | None = None
    lp_shares: int | None = None
    min_lp_shares: int | None = Field(default=None, ge=0)
    reason: str

    @model_validator(mode="after")
    def validate_action_fields(self) -> "LPDecision":
        if self.action == "ADD_LIQUIDITY":
            if self.amount_a is None or self.amount_a <= 0:
                raise ValueError("ADD_LIQUIDITY amount_a must be positive")
            if self.amount_b is None or self.amount_b <= 0:
                raise ValueError("ADD_LIQUIDITY amount_b must be positive")
        if self.action in {"REMOVE_LIQUIDITY", "COLLECT_FEES"}:
            if self.lp_shares is None or self.lp_shares <= 0:
                raise ValueError(f"{self.action} lp_shares must be positive")
        return self


def validate_lp_decision(decision: LPDecision, pools: list[PoolInfo]) -> LPDecision:
    if decision.action == "HOLD":
        return decision

    pool = next((candidate for candidate in pools if candidate.id == decision.pool_id), None)
    if pool is None:
        raise ValueError(f"unknown pool_id: {decision.pool_id}")

    return decision

