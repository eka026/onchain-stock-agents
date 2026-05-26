from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DashboardModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class SessionSummary(DashboardModel):
    agent_count: int = Field(alias="agentCount")
    event_count: int = Field(alias="eventCount")
    confirmed_tx_count: int = Field(alias="confirmedTxCount")
    rejected_count: int = Field(alias="rejectedCount")


class AgentSnapshot(DashboardModel):
    id: str
    type: Literal["trader", "lp"]
    label: str
    address: str
    balances: dict[str, str]


class PoolSnapshot(DashboardModel):
    id: str
    base_symbol: str = Field(alias="baseSymbol")
    quote_symbol: str = Field(alias="quoteSymbol")
    spot_price: str | None = Field(default=None, alias="spotPrice")
    reserve_a: str | None = Field(default=None, alias="reserveA")
    reserve_b: str | None = Field(default=None, alias="reserveB")
    fee_bps: int | None = Field(default=None, alias="feeBps")


class TimelineEvent(DashboardModel):
    id: str
    tick: int | None = None
    timestamp: datetime | None = None
    kind: Literal["news", "agent_decision", "validation", "transaction", "portfolio_update"]
    agent_id: str | None = Field(default=None, alias="agentId")
    agent_type: Literal["trader", "lp"] | None = Field(default=None, alias="agentType")
    pool_id: str | None = Field(default=None, alias="poolId")
    action: str | None = None
    status: Literal["ok", "rejected", "pending", "confirmed"] | None = None
    summary: str
    tx_hash: str | None = Field(default=None, alias="txHash")
    validation_reason: str | None = Field(default=None, alias="validationReason")
    portfolio_delta: dict[str, str] | None = Field(default=None, alias="portfolioDelta")


class Session(DashboardModel):
    id: str
    name: str
    source: Literal["sample", "imported", "mock-demo", "live-demo"]
    scenario_path: str | None = Field(default=None, alias="scenarioPath")
    network: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    summary: SessionSummary
    agents: list[AgentSnapshot]
    pools: list[PoolSnapshot]
    events: list[TimelineEvent]


class SessionListItem(DashboardModel):
    id: str
    name: str
    source: Literal["sample", "imported", "mock-demo", "live-demo"]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    summary: SessionSummary
