from types import SimpleNamespace

from agents.chain import ExecutionResult, ValidationResult
from agents.llm import LLMDecisionError, MockLLMClient
from agents.news_feed import NewsItem
from agents.portfolio import Portfolio
from agents.schemas import TraderDecision
from agents.trader_agent import TraderAgent, main
from test.test_chain_contracts import scenario


class FakeReader:
    def __init__(self):
        self.balances = {
            ("USD", "0xtrader"): 1_000,
            ("TECH", "0xtrader"): 5,
            ("FIN", "0xtrader"): 0,
        }
        self.reserves_by_pool = {
            "TECH-USD": (100, 200),
            "FIN-USD": (300, 900),
        }
        self.spot_prices = {
            "TECH-USD": 2 * 10**18,
            "FIN-USD": 3 * 10**18,
        }

    def token_balance(self, symbol, account):
        return self.balances.get((symbol, account), 0)

    def reserves(self, pool_id):
        return self.reserves_by_pool[pool_id]

    def spot_price(self, pool_id):
        return self.spot_prices[pool_id]

    def pool_fee_bps(self, pool_id):
        return 30

    def is_token_approved(self, symbol):
        return True

    def trader_policy(self, trader):
        return (True, 500, 1_000, 25, 123, 3600)

    def current_spent_amount(self, trader):
        return 25


class FakeValidator:
    def __init__(self, result=None):
        self.result = result or ValidationResult(ok=True)
        self.decisions = []

    def validate_trader_decision(self, trader, decision):
        self.decisions.append((trader, decision))
        return self.result


class FakeSubmitter:
    def __init__(self):
        self.built = []
        self.signed = []

    def build_swap_transaction(self, trader, decision, *, min_amount_out=None):
        self.built.append((trader, decision, min_amount_out))
        return {"function": "swap", "min_amount_out": min_amount_out}

    def sign_and_submit(self, transaction, private_key):
        self.signed.append((transaction, private_key))
        return "0xswap"


class FakeVerifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def verify_swap(self, tx_hash, pool_id):
        self.calls.append((tx_hash, pool_id))
        return self.result


def make_agent(*, llm_client=None, validator=None, verifier=None, portfolio=None):
    return TraderAgent(
        trader_address="0xtrader",
        private_key="0xprivate",
        scenario=scenario(),
        reader=FakeReader(),
        validator=validator or FakeValidator(),
        submitter=FakeSubmitter(),
        verifier=verifier
        or FakeVerifier(
            ExecutionResult(
                status="CONFIRMED",
                tx_hash="0xswap",
                action="SWAP",
                pool_id="TECH-USD",
                event_name="Swap",
                event_data={"tokenIn": "0xusd", "amountIn": 100, "amountOut": 45},
            )
        ),
        llm_client=llm_client or MockLLMClient(),
        portfolio=portfolio or Portfolio(balances={"USD": 1_000}),
    )


def test_trader_observes_news_pools_balances_and_policy():
    agent = make_agent()
    news = NewsItem(id=1, headline="Cloud demand improves", body="Server projects restarted.")

    observation = agent.observe(news)

    assert observation["news"] == {"id": 1, "headline": "Cloud demand improves", "body": "Server projects restarted."}
    assert observation["balances"]["USD"] == 1_000
    assert observation["policy"]["remaining_spending"] == 975
    assert observation["pools"][0]["id"] == "TECH-USD"
    assert observation["pools"][0]["reserve_a"] == 100
    assert observation["pools"][0]["spot_price"] == 2 * 10**18
    assert observation["pools"][0]["fee_bps"] == 30


def test_trader_hold_is_noop_after_validation():
    agent = make_agent(llm_client=MockLLMClient(trader_responses=[{"action": "HOLD", "reason": "wait"}]))

    result = agent.run_once()

    assert result.decision.action == "HOLD"
    assert result.tx_hash is None
    assert result.execution is None
    assert agent.submitter.built == []
    assert agent.portfolio.balances == {"USD": 1_000}


def test_trader_executes_swap_verifies_event_and_confirms_portfolio():
    agent = make_agent(
        llm_client=MockLLMClient(
            trader_responses=[
                {
                    "action": "SWAP",
                    "pool_id": "TECH-USD",
                    "token_in": "USD",
                    "amount_in": 100,
                    "max_slippage_bps": 100,
                    "reason": "buy tech",
                }
            ]
        )
    )

    result = agent.run_once()

    assert result.tx_hash == "0xswap"
    assert agent.submitter.built[0][2] == 32
    assert agent.verifier.calls == [("0xswap", "TECH-USD")]
    assert agent.portfolio.balances == {"USD": 900, "TECH": 45}
    assert agent.portfolio.pending == {}


def test_trader_confirmed_swap_keeps_zero_event_values():
    agent = make_agent()
    decision = TraderDecision(
        action="SWAP",
        pool_id="TECH-USD",
        token_in="USD",
        amount_in=100,
        reason="buy tech",
    )

    changes = agent._confirmed_swap_changes(
        decision,
        {"tokenIn": "0xusd", "amountIn": 0, "amountOut": 0},
    )

    assert changes == {"USD": 0, "TECH": 0}


def test_trader_rejected_execution_discards_pending_without_confirming():
    portfolio = Portfolio(balances={"USD": 1_000})
    agent = make_agent(
        llm_client=MockLLMClient(
            trader_responses=[
                {
                    "action": "SWAP",
                    "pool_id": "TECH-USD",
                    "token_in": "USD",
                    "amount_in": 100,
                    "reason": "buy tech",
                }
            ]
        ),
        verifier=FakeVerifier(
            ExecutionResult(
                status="REJECTED",
                tx_hash="0xswap",
                action="SWAP",
                pool_id="TECH-USD",
                reason="transaction reverted",
            )
        ),
        portfolio=portfolio,
    )

    result = agent.run_once()

    assert result.execution.status == "REJECTED"
    assert portfolio.balances == {"USD": 1_000}
    assert portfolio.pending == {}


def test_trader_pending_execution_keeps_pending_and_does_not_confirm():
    portfolio = Portfolio(balances={"USD": 1_000})
    agent = make_agent(
        llm_client=MockLLMClient(
            trader_responses=[
                {
                    "action": "SWAP",
                    "pool_id": "TECH-USD",
                    "token_in": "USD",
                    "amount_in": 100,
                    "reason": "buy tech",
                }
            ]
        ),
        verifier=FakeVerifier(
            ExecutionResult(
                status="PENDING",
                tx_hash="0xswap",
                action="SWAP",
                pool_id="TECH-USD",
                reason="receipt unavailable",
            )
        ),
        portfolio=portfolio,
    )

    result = agent.run_once()

    assert result.execution.status == "PENDING"
    assert portfolio.balances == {"USD": 1_000}
    assert "0xswap" in portfolio.pending


def test_trader_local_validation_failure_does_not_submit():
    agent = make_agent(
        llm_client=MockLLMClient(
            trader_responses=[
                {
                    "action": "SWAP",
                    "pool_id": "TECH-USD",
                    "token_in": "USD",
                    "amount_in": 100,
                    "reason": "buy tech",
                }
            ]
        ),
        validator=FakeValidator(ValidationResult(ok=False, reason="insufficient token allowance")),
    )

    result = agent.run_once()

    assert result.validation.ok is False
    assert result.validation.reason == "insufficient token allowance"
    assert result.tx_hash is None
    assert agent.submitter.built == []


def test_trader_llm_decision_error_is_rejected_without_crashing():
    class BadLLM:
        def decide_trader(self, observation):
            raise LLMDecisionError("invalid trader decision: token_in must be one of TECH, USD")

    agent = make_agent(llm_client=BadLLM())

    result = agent.run_once()

    assert result.decision.action == "HOLD"
    assert result.validation.ok is False
    assert result.validation.reason == "invalid trader decision: token_in must be one of TECH, USD"
    assert result.tx_hash is None
    assert result.execution is None
    assert agent.submitter.built == []


def test_main_once_uses_first_scheduled_news_and_prints_result(monkeypatch, capsys):
    class FakeFeed:
        def __init__(self, news, loaded_scenario):
            pass

        @staticmethod
        def load_news(path):
            return []

        def schedule(self):
            return [SimpleNamespace(news={"headline": "Cloud demand", "body": "Server spend"})]

    fake_agent = make_agent(llm_client=MockLLMClient(trader_responses=[{"action": "HOLD", "reason": "wait"}]))
    monkeypatch.setattr("agents.trader_agent.build_agent", lambda index, llm_override=None: fake_agent)
    monkeypatch.setattr("agents.trader_agent.NewsFeed", FakeFeed)

    exit_code = main(["--index", "0", "--once", "--llm", "mock"])

    assert exit_code == 0
    assert "execution_status" in capsys.readouterr().out
