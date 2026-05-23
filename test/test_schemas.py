import pytest
from pydantic import ValidationError

from agents.news_feed import PoolInfo
from agents.schemas import LPDecision, TraderDecision, validate_lp_decision, validate_trader_decision


def pools():
    return [
        PoolInfo(
            id="AAPL-USD",
            base_symbol="AAPL",
            quote_symbol="USD",
            pool_address="0xaaplpool",
        ),
        PoolInfo(
            id="NVDA-USD",
            base_symbol="NVDA",
            quote_symbol="USD",
            pool_address="0$nvdapool",
        ),
    ]


def test_hold_decision_is_valid_without_pool_or_token():
    decision = TraderDecision(action="HOLD", reason="No relevant news.")

    validated = validate_trader_decision(decision, pools())

    assert validated.action == "HOLD"


def test_swap_decision_accepts_known_pool_token_and_positive_amount():
    decision = TraderDecision(
        action="SWAP",
        pool_id="AAPL-USD",
        token_in="USD",
        amount_in=1_000,
        reason="The news appears positive for Apple.",
    )

    validated = validate_trader_decision(decision, pools())

    assert validated.pool_id == "AAPL-USD"
    assert validated.token_in == "USD"


def test_swap_decision_rejects_unknown_pool():
    decision = TraderDecision(
        action="SWAP",
        pool_id="TSLA-USD",
        token_in="USD",
        amount_in=1_000,
        reason="The news appears positive for Tesla.",
    )

    with pytest.raises(ValueError, match="unknown pool_id"):
        validate_trader_decision(decision, pools())


def test_swap_decision_rejects_token_not_in_pool():
    decision = TraderDecision(
        action="SWAP",
        pool_id="AAPL-USD",
        token_in="NVDA",
        amount_in=1_000,
        reason="Invalid token for selected pool.",
    )

    with pytest.raises(ValueError, match="token_in must be one of"):
        validate_trader_decision(decision, pools())


@pytest.mark.parametrize("amount", [0, -1])
def test_swap_decision_rejects_non_positive_amount(amount):
    with pytest.raises(ValidationError):
        TraderDecision(
            action="SWAP",
            pool_id="AAPL-USD",
            token_in="USD",
            amount_in=amount,
            reason="Invalid amount.",
        )


def test_lp_hold_decision_is_valid_without_pool():
    decision = LPDecision(action="HOLD", reason="No liquidity action needed.")

    validated = validate_lp_decision(decision, pools())

    assert validated.action == "HOLD"


def test_lp_add_liquidity_accepts_known_pool_and_positive_amounts():
    decision = LPDecision(
        action="ADD_LIQUIDITY",
        pool_id="NVDA-USD",
        amount_a=1_000,
        amount_b=2_000,
        reason="Adding liquidity to active pool.",
    )

    validated = validate_lp_decision(decision, pools())

    assert validated.pool_id == "NVDA-USD"


def test_lp_remove_liquidity_accepts_known_pool_and_positive_shares():
    decision = LPDecision(
        action="REMOVE_LIQUIDITY",
        pool_id="AAPL-USD",
        lp_shares=100,
        reason="Reducing exposure.",
    )

    validated = validate_lp_decision(decision, pools())

    assert validated.lp_shares == 100


def test_lp_collect_fees_accepts_known_pool_and_positive_shares():
    decision = LPDecision(
        action="COLLECT_FEES",
        pool_id="AAPL-USD",
        lp_shares=100,
        reason="Collecting accumulated fees.",
    )

    validated = validate_lp_decision(decision, pools())

    assert validated.action == "COLLECT_FEES"


def test_lp_decision_rejects_unknown_pool():
    decision = LPDecision(
        action="COLLECT_FEES",
        pool_id="TSLA-USD",
        lp_shares=100,
        reason="Unknown pool.",
    )

    with pytest.raises(ValueError, match="unknown pool_id"):
        validate_lp_decision(decision, pools())


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "ADD_LIQUIDITY", "pool_id": "AAPL-USD", "amount_a": 0, "amount_b": 1, "reason": "bad"},
        {"action": "ADD_LIQUIDITY", "pool_id": "AAPL-USD", "amount_a": 1, "amount_b": -1, "reason": "bad"},
        {"action": "REMOVE_LIQUIDITY", "pool_id": "AAPL-USD", "lp_shares": 0, "reason": "bad"},
        {"action": "COLLECT_FEES", "pool_id": "AAPL-USD", "lp_shares": -1, "reason": "bad"},
    ],
)
def test_lp_decision_rejects_non_positive_amounts(payload):
    with pytest.raises(ValidationError):
        LPDecision(**payload)

