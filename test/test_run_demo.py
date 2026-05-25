from types import SimpleNamespace

import pytest

from agents.chain import ExecutionResult, ValidationResult
from agents.llm import MockLLMClient
from agents.lp_agent import LPAgent
from agents.news_feed import NewsItem, ScheduledNews
from agents.portfolio import Portfolio
from agents.run_demo import _first_unapproved_pool_symbol, build_demo_agents, main, run_demo
from agents.trader_agent import TraderAgent
from test.test_chain_contracts import scenario
from test.test_lp_agent import FakeReader as LPReader
from test.test_lp_agent import FakeSubmitter as LPSubmitter
from test.test_lp_agent import FakeVerifier as LPVerifier
from test.test_trader_agent import FakeReader as TraderReader
from test.test_trader_agent import FakeSubmitter as TraderSubmitter
from test.test_trader_agent import FakeVerifier as TraderVerifier


class FakeFeed:
    def __init__(self):
        self.news = NewsItem(
            id=1,
            headline="Cloud demand improves",
            body="Server projects restarted.",
        )

    def schedule(self):
        return [ScheduledNews(tick=2, news=self.news)]

    def broadcast_at(self, tick, trader_ids):
        if tick != 2:
            return {}
        return {trader_id: self.news for trader_id in trader_ids}


class DemoTraderReader(TraderReader):
    def is_token_approved(self, symbol):
        return symbol != "TECH"


class DemoTraderValidator:
    def validate_trader_decision(self, trader, decision):
        if decision.action == "HOLD":
            return ValidationResult(ok=True)
        if trader.lower().endswith("dead"):
            return ValidationResult(ok=False, reason="trader policy is disabled")
        if decision.token_in == "TECH":
            return ValidationResult(ok=False, reason="token is not approved")
        if (decision.amount_in or 0) > 500:
            return ValidationResult(ok=False, reason="swap exceeds max swap amount")
        return ValidationResult(ok=True)


class DemoLPValidator:
    def validate_lp_decision(self, lp, decision):
        if decision.action == "HOLD":
            return ValidationResult(ok=True)
        if lp != "0xlp":
            return ValidationResult(ok=False, reason="LP policy is disabled")
        if decision.action == "COLLECT_FEES" and (decision.lp_shares or 0) > 700:
            return ValidationResult(ok=False, reason="fee withdrawal exceeds policy limit")
        if decision.action == "ADD_LIQUIDITY" and ((decision.amount_a or 0) > 500 or (decision.amount_b or 0) > 500):
            return ValidationResult(ok=False, reason="liquidity add exceeds policy limit")
        return ValidationResult(ok=True)


def make_lp_agent():
    return LPAgent(
        lp_address="0xlp",
        private_key="0xprivate",
        scenario=scenario(),
        reader=LPReader(),
        validator=DemoLPValidator(),
        submitter=LPSubmitter(),
        verifier=LPVerifier(
            ExecutionResult(
                status="CONFIRMED",
                tx_hash="0xlpaction",
                action="ADD_LIQUIDITY",
                pool_id="TECH-USD",
                event_name="LiquidityAdded",
                event_data={"amountA": 10, "amountB": 20, "lpShares": 14},
            )
        ),
        llm_client=MockLLMClient(),
        portfolio=Portfolio(balances={"USD": 1_000, "TECH": 50, "TECH-USD-LP": 70}),
    )


def make_trader_agent(address):
    return TraderAgent(
        trader_address=address,
        private_key="0xprivate",
        scenario=scenario(),
        reader=DemoTraderReader(),
        validator=DemoTraderValidator(),
        submitter=TraderSubmitter(),
        verifier=TraderVerifier(
            ExecutionResult(
                status="CONFIRMED",
                tx_hash="0xswap",
                action="SWAP",
                pool_id="TECH-USD",
                event_name="Swap",
                event_data={"tokenIn": "0xusd", "amountIn": 100, "amountOut": 45},
            )
        ),
        llm_client=MockLLMClient(trader_responses=[{"action": "SWAP", "pool_id": "TECH-USD", "token_in": "USD", "amount_in": 100, "reason": "buy"}]),
        portfolio=Portfolio(balances={"USD": 1_000}),
    )


def test_run_demo_orchestrates_liquidity_news_traders_fees_negative_scenarios_and_portfolios():
    lp_agent = make_lp_agent()
    traders = [make_trader_agent("0xtrader"), make_trader_agent("0xtrader2")]

    result = run_demo(
        scenario_path="data/scenarios/demo.json",
        llm_override="mock",
        lp_agent=lp_agent,
        trader_agents=traders,
        news_feed=FakeFeed(),
    )

    assert result.initial_liquidity.decision.action == "ADD_LIQUIDITY"
    assert [(tick, trader) for tick, trader, _ in result.trader_results] == [(2, "0xtrader"), (2, "0xtrader2")]
    assert [item[2].decision.action for item in result.trader_results] == ["SWAP", "SWAP"]
    assert result.fee_collection.decision.action == "COLLECT_FEES"
    assert result.liquidity_removal.decision.action == "REMOVE_LIQUIDITY"
    assert [negative.name for negative in result.negative_results] == [
        "oversized_swap",
        "unapproved_token_swap",
        "disabled_trader_swap",
        "fee_withdrawal_limit",
        "disabled_lp_action",
    ]
    assert [negative.result.validation.ok for negative in result.negative_results] == [False, False, False, False, False]
    assert result.final_portfolios["trader:0xtrader"]["USD"] == 900
    assert result.final_portfolios["trader:0xtrader2"]["TECH"] == 45


def test_demo_lp_lifecycle_does_not_depend_on_mock_lp_action():
    class SpyLLM(MockLLMClient):
        calls = 0

        def decide_lp(self, observation):
            self.calls += 1
            return super().decide_lp(observation)

    lp_agent = make_lp_agent()
    spy_llm = SpyLLM()
    lp_agent.llm_client = spy_llm

    result = run_demo(
        scenario_path="data/scenarios/demo.json",
        llm_override="mock",
        lp_agent=lp_agent,
        trader_agents=[make_trader_agent("0xtrader"), make_trader_agent("0xtrader2")],
        news_feed=FakeFeed(),
    )

    assert result.initial_liquidity.decision.action == "ADD_LIQUIDITY"
    assert result.fee_collection.decision.action == "COLLECT_FEES"
    assert result.liquidity_removal.decision.action == "REMOVE_LIQUIDITY"
    assert spy_llm.calls == 0


def test_run_demo_low_gas_skips_lp_lifecycle_and_runs_one_trader_transaction():
    lp_agent = make_lp_agent()
    traders = [make_trader_agent("0xtrader"), make_trader_agent("0xtrader2")]

    result = run_demo(
        scenario_path="data/scenarios/demo.json",
        llm_override="mock",
        lp_agent=lp_agent,
        trader_agents=traders,
        news_feed=FakeFeed(),
        low_gas=True,
    )

    assert result.initial_liquidity is None
    assert [(tick, trader) for tick, trader, _ in result.trader_results] == [(2, "0xtrader")]
    assert result.trader_results[0][2].tx_hash == "0xswap"
    assert result.negative_results == []
    assert result.fee_collection is None
    assert result.liquidity_removal is None


def test_first_unapproved_pool_symbol_continues_after_reader_exception():
    class Reader:
        def is_token_approved(self, symbol):
            if symbol == "TECH":
                raise RuntimeError("temporary read failure")
            return False

    trader = SimpleNamespace(reader=Reader())
    pool = SimpleNamespace(base_symbol="TECH", quote_symbol="USD")

    assert _first_unapproved_pool_symbol(trader, pool) == "USD"


def test_run_demo_requires_two_traders():
    with pytest.raises(RuntimeError, match="at least two trader agents"):
        run_demo(
            scenario_path="data/scenarios/demo.json",
            lp_agent=make_lp_agent(),
            trader_agents=[make_trader_agent("0xtrader")],
            news_feed=FakeFeed(),
        )


def test_build_demo_agents_uses_scenario_override_and_mock_llm(monkeypatch):
    loaded = SimpleNamespace(
        rpc_url="https://example.invalid",
        scenario=scenario(),
        traders=[
            SimpleNamespace(private_key="0xtrader1", model="model-a"),
            SimpleNamespace(private_key="0xtrader2", model="model-b"),
        ],
        lps=[SimpleNamespace(private_key="0xlp", model="model-lp")],
        openai_api_key=None,
        google_api_key=None,
        groq_api_key=None,
    )
    calls = []

    class FakeAccount:
        def from_key(self, key):
            return SimpleNamespace(address=f"addr:{key}")

    class FakeEth:
        account = FakeAccount()

    class FakeRegistry:
        web3 = SimpleNamespace(eth=FakeEth())

        @classmethod
        def from_rpc(cls, loaded_scenario, rpc_url):
            calls.append((loaded_scenario, rpc_url))
            return cls()

    monkeypatch.setattr("agents.run_demo.config.load", lambda scenario_path=None: loaded)
    monkeypatch.setattr("agents.run_demo.ContractRegistry", FakeRegistry)
    monkeypatch.setattr("agents.run_demo.ChainReader", lambda registry: object())
    monkeypatch.setattr("agents.run_demo.LocalValidator", lambda reader: object())
    monkeypatch.setattr("agents.run_demo.ChainTransactionSubmitter", lambda registry: object())
    monkeypatch.setattr("agents.run_demo.ReceiptVerifier", lambda registry: object())

    lp_agent, trader_agents, loaded_scenario = build_demo_agents(scenario_path="custom.json", llm_override="mock")

    assert calls == [(scenario(), "https://example.invalid")]
    assert loaded_scenario == scenario()
    assert lp_agent.lp_address == "addr:0xlp"
    assert [agent.trader_address for agent in trader_agents] == ["addr:0xtrader1", "addr:0xtrader2"]


def test_build_demo_agents_rejects_placeholder_scenario_addresses(monkeypatch):
    placeholder_scenario = scenario().model_copy(
        update={"policy_address": "0x0000000000000000000000000000000000000100"}
    )
    loaded = SimpleNamespace(
        rpc_url="https://example.invalid",
        scenario=placeholder_scenario,
        traders=[
            SimpleNamespace(private_key="0xtrader1", model="model-a"),
            SimpleNamespace(private_key="0xtrader2", model="model-b"),
        ],
        lps=[SimpleNamespace(private_key="0xlp", model="model-lp")],
        openai_api_key=None,
        google_api_key=None,
        groq_api_key=None,
    )
    monkeypatch.setattr("agents.run_demo.config.load", lambda scenario_path=None: loaded)

    with pytest.raises(RuntimeError, match="placeholder contract addresses"):
        build_demo_agents(scenario_path="data/scenarios/demo.json", llm_override="mock")


def test_main_prints_demo_result(monkeypatch, capsys):
    monkeypatch.setattr(
        "agents.run_demo.run_demo",
        lambda scenario_path, llm_override=None, low_gas=False: run_demo(
            scenario_path=scenario_path,
            llm_override=llm_override,
            lp_agent=make_lp_agent(),
            trader_agents=[make_trader_agent("0xtrader"), make_trader_agent("0xtrader2")],
            news_feed=FakeFeed(),
            low_gas=low_gas,
        ),
    )

    exit_code = main(["--scenario", "data/scenarios/demo.json", "--llm", "mock"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "final_portfolios" in output
    assert "negative:oversized_swap" in output
