from agents.chain import ExecutionResult, ValidationResult
from agents.llm import MockLLMClient
from agents.lp_agent import LPAgent, main
from agents.portfolio import Portfolio
from agents.schemas import LPDecision
from test.test_chain_contracts import scenario


class FakeReader:
    def __init__(self):
        self.balances = {
            ("USD", "0xlp"): 1_000,
            ("TECH", "0xlp"): 50,
            ("FIN", "0xlp"): 20,
        }
        self.lp_balances = {
            ("TECH-USD", "0xlp"): 70,
            ("FIN-USD", "0xlp"): 30,
        }
        self.reserves_by_pool = {
            "TECH-USD": (100, 200),
            "FIN-USD": (300, 900),
        }
        self.spot_prices = {
            "TECH-USD": 2 * 10**18,
            "FIN-USD": 3 * 10**18,
        }
        self.fees = {
            "TECH-USD": (7, 11),
            "FIN-USD": (13, 17),
        }
        self.total_supply = {
            "TECH-USD": 700,
            "FIN-USD": 300,
        }

    def token_balance(self, symbol, account):
        return self.balances.get((symbol, account), 0)

    def lp_balance(self, pool_id, account):
        return self.lp_balances.get((pool_id, account), 0)

    def lp_total_supply(self, pool_id):
        return self.total_supply[pool_id]

    def reserves(self, pool_id):
        return self.reserves_by_pool[pool_id]

    def spot_price(self, pool_id):
        return self.spot_prices[pool_id]

    def vault_fees(self, pool_id):
        return self.fees[pool_id]

    def lp_policy(self, lp):
        return (True, 500, 300, 50, 10, 123, 3600)

    def current_fee_withdrawn(self, lp):
        return 10


class FakeValidator:
    def __init__(self, result=None):
        self.result = result or ValidationResult(ok=True)
        self.decisions = []

    def validate_lp_decision(self, lp, decision):
        self.decisions.append((lp, decision))
        return self.result


class FakeSubmitter:
    def __init__(self):
        self.built = []
        self.signed = []

    def build_add_liquidity_transaction(self, lp, decision):
        self.built.append(("ADD_LIQUIDITY", lp, decision))
        return {"function": "addLiquidity"}

    def build_remove_liquidity_transaction(self, lp, decision):
        self.built.append(("REMOVE_LIQUIDITY", lp, decision))
        return {"function": "removeLiquidity"}

    def build_collect_fees_transaction(self, lp, decision):
        self.built.append(("COLLECT_FEES", lp, decision))
        return {"function": "collectFees"}

    def sign_and_submit(self, transaction, private_key):
        self.signed.append((transaction, private_key))
        return "0xlpaction"


class FakeVerifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def verify_add_liquidity(self, tx_hash, pool_id):
        self.calls.append(("ADD_LIQUIDITY", tx_hash, pool_id))
        return self.result

    def verify_remove_liquidity(self, tx_hash, pool_id):
        self.calls.append(("REMOVE_LIQUIDITY", tx_hash, pool_id))
        return self.result

    def verify_collect_fees(self, tx_hash, pool_id):
        self.calls.append(("COLLECT_FEES", tx_hash, pool_id))
        return self.result


def make_agent(*, llm_client=None, validator=None, verifier=None, portfolio=None):
    submitter = FakeSubmitter()
    agent = LPAgent(
        lp_address="0xlp",
        private_key="0xprivate",
        scenario=scenario(),
        reader=FakeReader(),
        validator=validator or FakeValidator(),
        submitter=submitter,
        verifier=verifier
        or FakeVerifier(
            ExecutionResult(
                status="CONFIRMED",
                tx_hash="0xlpaction",
                action="ADD_LIQUIDITY",
                pool_id="TECH-USD",
                event_name="LiquidityAdded",
                event_data={"amountA": 10, "amountB": 20, "lpShares": 14},
            )
        ),
        llm_client=llm_client or MockLLMClient(lp_responses=[{"action": "HOLD", "reason": "wait"}]),
        portfolio=portfolio or Portfolio(balances={"USD": 1_000, "TECH": 50, "TECH-USD-LP": 70}),
    )
    return agent


def test_lp_observes_pools_balances_fees_and_policy():
    agent = make_agent()

    observation = agent.observe()

    assert observation["agent_type"] == "lp"
    assert observation["balances"]["USD"] == 1_000
    assert observation["balances"]["TECH-USD-LP"] == 70
    assert observation["accumulated_fees"]["TECH-USD"] == {"TECH": 7, "USD": 11}
    assert observation["policy"]["remaining_fee_withdrawal"] == 40
    assert observation["pools"][0]["reserve_a"] == 100
    assert observation["pools"][0]["spot_price"] == 2 * 10**18
    assert observation["pools"][0]["lp_total_supply"] == 700


def test_lp_hold_is_noop_after_validation():
    agent = make_agent(llm_client=MockLLMClient(lp_responses=[{"action": "HOLD", "reason": "wait"}]))

    result = agent.run_once()

    assert result.decision.action == "HOLD"
    assert result.tx_hash is None
    assert result.execution is None
    assert agent.submitter.built == []
    assert agent.portfolio.balances == {"USD": 1_000, "TECH": 50, "TECH-USD-LP": 70}


def test_lp_executes_add_liquidity_verifies_event_and_confirms_portfolio():
    agent = make_agent(
        llm_client=MockLLMClient(
            lp_responses=[
                {
                    "action": "ADD_LIQUIDITY",
                    "pool_id": "TECH-USD",
                    "amount_a": 10,
                    "amount_b": 20,
                    "min_lp_shares": 1,
                    "reason": "add",
                }
            ]
        )
    )

    result = agent.run_once()

    assert result.tx_hash == "0xlpaction"
    assert agent.submitter.built[0][0] == "ADD_LIQUIDITY"
    assert agent.verifier.calls == [("ADD_LIQUIDITY", "0xlpaction", "TECH-USD")]
    assert agent.portfolio.balances == {"USD": 980, "TECH": 40, "TECH-USD-LP": 84}
    assert agent.portfolio.pending == {}


def test_lp_confirmed_add_liquidity_keeps_zero_event_values():
    agent = make_agent()
    decision = LPDecision(
        action="ADD_LIQUIDITY",
        pool_id="TECH-USD",
        amount_a=10,
        amount_b=20,
        reason="add",
    )

    changes = agent._confirmed_changes(decision, {"amountA": 0, "amountB": 0, "lpShares": 0})

    assert changes == {"TECH": 0, "USD": 0, "TECH-USD-LP": 0}


def test_lp_executes_remove_liquidity_verifies_event_and_confirms_portfolio():
    agent = make_agent(
        llm_client=MockLLMClient(
            lp_responses=[
                {
                    "action": "REMOVE_LIQUIDITY",
                    "pool_id": "TECH-USD",
                    "lp_shares": 7,
                    "reason": "remove",
                }
            ]
        ),
        verifier=FakeVerifier(
            ExecutionResult(
                status="CONFIRMED",
                tx_hash="0xlpaction",
                action="REMOVE_LIQUIDITY",
                pool_id="TECH-USD",
                event_name="LiquidityRemoved",
                event_data={"amountA": 5, "amountB": 9, "lpShares": 7},
            )
        ),
    )

    result = agent.run_once()

    assert result.tx_hash == "0xlpaction"
    assert agent.submitter.built[0][0] == "REMOVE_LIQUIDITY"
    assert agent.verifier.calls == [("REMOVE_LIQUIDITY", "0xlpaction", "TECH-USD")]
    assert agent.portfolio.balances == {"USD": 1_009, "TECH": 55, "TECH-USD-LP": 63}


def test_lp_executes_collect_fees_verifies_event_and_confirms_portfolio():
    agent = make_agent(
        llm_client=MockLLMClient(
            lp_responses=[
                {
                    "action": "COLLECT_FEES",
                    "pool_id": "TECH-USD",
                    "lp_shares": 7,
                    "reason": "collect",
                }
            ]
        ),
        verifier=FakeVerifier(
            ExecutionResult(
                status="CONFIRMED",
                tx_hash="0xlpaction",
                action="COLLECT_FEES",
                pool_id="TECH-USD",
                event_name="FeesCollected",
                event_data={"feesA": 2, "feesB": 3},
            )
        ),
    )

    result = agent.run_once()

    assert result.tx_hash == "0xlpaction"
    assert agent.submitter.built[0][0] == "COLLECT_FEES"
    assert agent.verifier.calls == [("COLLECT_FEES", "0xlpaction", "TECH-USD")]
    assert agent.portfolio.balances == {"USD": 1_003, "TECH": 52, "TECH-USD-LP": 70}


def test_lp_rejected_execution_discards_pending_without_confirming():
    portfolio = Portfolio(balances={"USD": 1_000, "TECH": 50, "TECH-USD-LP": 70})
    agent = make_agent(
        llm_client=MockLLMClient(
            lp_responses=[
                {
                    "action": "ADD_LIQUIDITY",
                    "pool_id": "TECH-USD",
                    "amount_a": 10,
                    "amount_b": 20,
                    "reason": "add",
                }
            ]
        ),
        verifier=FakeVerifier(
            ExecutionResult(
                status="REJECTED",
                tx_hash="0xlpaction",
                action="ADD_LIQUIDITY",
                pool_id="TECH-USD",
                reason="transaction reverted",
            )
        ),
        portfolio=portfolio,
    )

    result = agent.run_once()

    assert result.execution.status == "REJECTED"
    assert portfolio.balances == {"USD": 1_000, "TECH": 50, "TECH-USD-LP": 70}
    assert portfolio.pending == {}


def test_lp_pending_execution_keeps_pending_and_does_not_confirm():
    portfolio = Portfolio(balances={"USD": 1_000, "TECH": 50, "TECH-USD-LP": 70})
    agent = make_agent(
        llm_client=MockLLMClient(
            lp_responses=[
                {
                    "action": "REMOVE_LIQUIDITY",
                    "pool_id": "TECH-USD",
                    "lp_shares": 7,
                    "reason": "remove",
                }
            ]
        ),
        verifier=FakeVerifier(
            ExecutionResult(
                status="PENDING",
                tx_hash="0xlpaction",
                action="REMOVE_LIQUIDITY",
                pool_id="TECH-USD",
                reason="receipt unavailable",
            )
        ),
        portfolio=portfolio,
    )

    result = agent.run_once()

    assert result.execution.status == "PENDING"
    assert portfolio.balances == {"USD": 1_000, "TECH": 50, "TECH-USD-LP": 70}
    assert "0xlpaction" in portfolio.pending


def test_lp_local_validation_failure_does_not_submit():
    agent = make_agent(
        llm_client=MockLLMClient(
            lp_responses=[
                {
                    "action": "COLLECT_FEES",
                    "pool_id": "TECH-USD",
                    "lp_shares": 7,
                    "reason": "collect",
                }
            ]
        ),
        validator=FakeValidator(ValidationResult(ok=False, reason="fee withdrawal exceeds policy limit")),
    )

    result = agent.run_once()

    assert result.validation.ok is False
    assert result.validation.reason == "fee withdrawal exceeds policy limit"
    assert result.tx_hash is None
    assert agent.submitter.built == []


def test_main_once_prints_result(monkeypatch, capsys):
    fake_agent = make_agent(llm_client=MockLLMClient(lp_responses=[{"action": "HOLD", "reason": "wait"}]))
    monkeypatch.setattr("agents.lp_agent.build_agent", lambda index, llm_override=None: fake_agent)

    exit_code = main(["--index", "0", "--once", "--llm", "mock"])

    assert exit_code == 0
    assert "execution_status" in capsys.readouterr().out
