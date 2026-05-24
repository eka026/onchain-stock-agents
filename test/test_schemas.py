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
            lp_token_address="0xaapllp",
            vault_address="0xaaplvault",
        ),
        PoolInfo(
            id="NVDA-USD",
            base_symbol="NVDA",
            quote_symbol="USD",
            pool_address="0$nvdapool",
            lp_token_address="0$nvdalp",
            vault_address="0$nvdavault",
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
        max_slippage_bps=100,
        deadline_seconds=60,
        reason="The news appears positive for Apple.",
    )

    validated = validate_trader_decision(decision, pools())

    assert validated.pool_id == "AAPL-USD"
    assert validated.token_in == "USD"
    assert validated.max_slippage_bps == 100
    assert validated.deadline_seconds == 60


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


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "SWAP", "token_in": "USD", "amount_in": 1, "reason": "missing pool"},
        {"action": "SWAP", "pool_id": "AAPL-USD", "amount_in": 1, "reason": "missing token"},
    ],
)
def test_swap_decision_requires_pool_and_token_at_parse_time(payload):
    with pytest.raises(ValidationError):
        TraderDecision(**payload)


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
        min_lp_shares=500,
        reason="Adding liquidity to active pool.",
    )

    validated = validate_lp_decision(decision, pools())

    assert validated.pool_id == "NVDA-USD"
    assert validated.min_lp_shares == 500


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


@pytest.mark.parametrize(
    "payload",
    [
        {
            "action": "SWAP",
            "pool_id": "AAPL-USD",
            "token_in": "USD",
            "amount_in": 1,
            "max_slippage_bps": -1,
            "reason": "bad",
        },
        {
            "action": "SWAP",
            "pool_id": "AAPL-USD",
            "token_in": "USD",
            "amount_in": 1,
            "max_slippage_bps": 10_001,
            "reason": "bad",
        },
        {
            "action": "SWAP",
            "pool_id": "AAPL-USD",
            "token_in": "USD",
            "amount_in": 1,
            "deadline_seconds": 0,
            "reason": "bad",
        },
    ],
)
def test_trader_decision_rejects_invalid_optional_execution_fields(payload):
    with pytest.raises(ValidationError):
        TraderDecision(**payload)


def test_lp_decision_rejects_negative_min_lp_shares():
    with pytest.raises(ValidationError):
        LPDecision(
            action="ADD_LIQUIDITY",
            pool_id="AAPL-USD",
            amount_a=1,
            amount_b=1,
            min_lp_shares=-1,
            reason="bad",
        )

