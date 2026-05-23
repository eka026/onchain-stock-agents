import pytest
from pydantic import ValidationError

from agents.news_feed import PoolInfo
from agents.schemas import TraderDecision, validate_trader_decision


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

