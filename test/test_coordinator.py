from agents.chain import ExecutionResult, ValidationResult
from agents.coordinator import CycleCoordinator
from agents.lp_agent import LPRunResult
from agents.news_feed import NewsItem
from agents.schemas import LPDecision, TraderDecision
from agents.trader_agent import TraderRunResult


class FakeReader:
    def __init__(self):
        self.cache_enabled = False
        self.events = []

    def enable_cache(self):
        self.cache_enabled = True
        self.events.append("enable")

    def reset_cache(self):
        self.cache_enabled = False
        self.events.append("reset")


class FakeTrader:
    def __init__(self, reader, address="0xtrader", execution_log=None):
        self.reader = reader
        self.trader_address = address
        self.observed_news = None
        self.execution_log = execution_log

    def observe(self, news=None):
        self.observed_news = news
        return {"agent_type": "trader", "cache_enabled": self.reader.cache_enabled, "news": news.model_dump()}

    def decide(self, observation):
        assert observation["cache_enabled"] is True
        return TraderDecision(action="HOLD", reason="cycle test")

    def execute(self, decision):
        if self.execution_log is not None:
            self.execution_log.append(self.trader_address)
        return TraderRunResult(
            decision=decision,
            tx_hash=None,
            execution=None,
            validation=ValidationResult(ok=True),
        )


class FakeLP:
    lp_address = "0xlp"

    def __init__(self, reader):
        self.reader = reader

    def observe(self):
        return {"agent_type": "lp", "cache_enabled": self.reader.cache_enabled}

    def decide(self, observation):
        assert observation["cache_enabled"] is True
        return LPDecision(action="HOLD", reason="cycle test")

    def execute(self, decision):
        return LPRunResult(
            decision=decision,
            tx_hash=None,
            execution=ExecutionResult(status="PENDING", tx_hash="0x0", action="HOLD"),
            validation=ValidationResult(ok=True),
        )


class FakeFeed:
    def __init__(self):
        self.news = NewsItem(id=1, headline="TECH headline", body="TECH body")

    def broadcast_at(self, tick, trader_ids):
        assert tick == 3
        return {trader_id: self.news for trader_id in trader_ids}


def test_cycle_coordinator_enables_cache_for_cycle_and_resets_afterward():
    reader = FakeReader()
    trader = FakeTrader(reader)
    lp_agent = FakeLP(reader)
    coordinator = CycleCoordinator(
        traders=[trader],
        lp_agents=[lp_agent],
        reader=reader,
        news_feed=FakeFeed(),
        min_cycle_seconds=60,
        shuffle_execution=False,
    )

    result = coordinator.run_cycle(tick=3)

    assert reader.events == ["reset", "enable", "reset"]
    assert reader.cache_enabled is False
    assert trader.observed_news.headline == "TECH headline"
    assert result.tick == 3
    assert [(item.agent_type, item.address, item.decision.action) for item in result.agents] == [
        ("trader", "0xtrader", "HOLD"),
        ("lp", "0xlp", "HOLD"),
    ]


def test_cycle_coordinator_shuffles_execution_order_with_seed():
    reader = FakeReader()
    execution_log = []
    traders = [
        FakeTrader(reader, address="0xtrader-a", execution_log=execution_log),
        FakeTrader(reader, address="0xtrader-b", execution_log=execution_log),
        FakeTrader(reader, address="0xtrader-c", execution_log=execution_log),
    ]
    coordinator = CycleCoordinator(
        traders=traders,
        lp_agents=[],
        reader=reader,
        news_feed=FakeFeed(),
        min_cycle_seconds=60,
        shuffle_execution=True,
        shuffle_seed=7,
    )

    coordinator.run_cycle(tick=3)

    assert sorted(execution_log) == ["0xtrader-a", "0xtrader-b", "0xtrader-c"]
    assert execution_log != ["0xtrader-a", "0xtrader-b", "0xtrader-c"]
