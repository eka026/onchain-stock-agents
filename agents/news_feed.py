import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NewsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    headline: str
    body: str


class TokenInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    address: str


class PoolInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    base_symbol: str
    quote_symbol: str
    pool_address: str
    lp_token_address: str
    vault_address: str

    def symbols(self) -> set[str]:
        return {self.base_symbol, self.quote_symbol}


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int
    news_file: str
    policy_address: str
    min_interval_ticks: int = Field(gt=0)
    max_interval_ticks: int = Field(gt=0)
    max_events: int = Field(gt=0)
    broadcast_to_all_traders: bool = True
    tokens: list[TokenInfo]
    pools: list[PoolInfo]

    @model_validator(mode="after")
    def validate_intervals_and_markets(self) -> "Scenario":
        if self.min_interval_ticks > self.max_interval_ticks:
            raise ValueError("min_interval_ticks must be <= max_interval_ticks")

        token_symbols = {token.symbol for token in self.tokens}
        for pool in self.pools:
            missing = pool.symbols() - token_symbols
            if missing:
                missing_symbols = ", ".join(sorted(missing))
                raise ValueError(f"pool {pool.id} references unknown token symbols: {missing_symbols}")
        return self


@dataclass(frozen=True)
class ScheduledNews:
    tick: int
    news: NewsItem


class NewsFeed:
    def __init__(self, news: Iterable[NewsItem], scenario: Scenario):
        self.news = list(news)
        self.scenario = scenario
        self._schedule: list[ScheduledNews] | None = None

    @staticmethod
    def load_news(path: str | Path) -> list[NewsItem]:
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        return [NewsItem.model_validate(record) for record in records]

    @staticmethod
    def load_scenario(path: str | Path) -> Scenario:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        return Scenario.model_validate(record)

    def schedule(self) -> list[ScheduledNews]:
        if self._schedule is not None:
            return list(self._schedule)

        rng = random.Random(self.scenario.seed)
        selected = list(self.news)
        rng.shuffle(selected)
        selected = selected[: min(self.scenario.max_events, len(selected))]

        tick = 0
        events: list[ScheduledNews] = []
        for item in selected:
            tick += rng.randint(self.scenario.min_interval_ticks, self.scenario.max_interval_ticks)
            events.append(ScheduledNews(tick=tick, news=item))

        self._schedule = events
        return list(events)

    def broadcast_at(self, tick: int, trader_ids: Iterable[str]) -> dict[str, NewsItem]:
        event = next((scheduled for scheduled in self.schedule() if scheduled.tick == tick), None)
        if event is None:
            return {}
        if not self.scenario.broadcast_to_all_traders:
            raise ValueError("scenario must enable broadcast_to_all_traders")
        return {trader_id: event.news for trader_id in trader_ids}

