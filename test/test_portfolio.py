import pytest

from agents.portfolio import Portfolio


def test_pending_does_not_mutate_confirmed_balances():
    p = Portfolio(balances={"USD": 1_000, "NVDA": 10})

    p.record_pending("0xswap", "SWAP", {"USD": -250, "NVDA": 5})

    assert p.balances == {"USD": 1_000, "NVDA": 10}


def test_confirmed_swap_applies_token_deltas():
    p = Portfolio(balances={"USD": 1_000})

    p.record_pending("0xswap", "SWAP", {"USD": -250, "NVDA": 5})
    p.confirm("0xswap")

    assert p.balances == {"USD": 750, "NVDA": 5}
    assert "0xswap" not in p.pending


def test_confirmed_liquidity_add_decreases_tokens_and_increases_lp_shares():
    p = Portfolio(balances={"USD": 1_000, "NVDA": 20})

    p.record_pending("0xadd", "ADD_LIQUIDITY", {"USD": -500, "NVDA": -10, "NVDA-USD-LP": 70})
    p.confirm("0xadd")

    assert p.balances == {"USD": 500, "NVDA": 10, "NVDA-USD-LP": 70}


def test_confirmed_liquidity_remove_increases_tokens_and_decreases_lp_shares():
    p = Portfolio(balances={"USD": 500, "NVDA": 10, "NVDA-USD-LP": 70})

    p.record_pending("0xremove", "REMOVE_LIQUIDITY", {"USD": 250, "NVDA": 5, "NVDA-USD-LP": -35})
    p.confirm("0xremove")

    assert p.balances == {"USD": 750, "NVDA": 15, "NVDA-USD-LP": 35}


def test_confirmed_fee_collection_increases_fee_token_balances():
    p = Portfolio(balances={"USD": 500, "NVDA": 10, "NVDA-USD-LP": 70})

    p.record_pending("0xfees", "COLLECT_FEES", {"USD": 12, "NVDA": 1})
    p.confirm("0xfees")

    assert p.balances == {"USD": 512, "NVDA": 11, "NVDA-USD-LP": 70}


def test_zero_balance_is_removed_after_confirmation():
    p = Portfolio(balances={"USD": 100})

    p.record_pending("0xall", "SWAP", {"USD": -100, "NVDA": 2})
    p.confirm("0xall")

    assert p.balances == {"NVDA": 2}


def test_discard_removes_pending_without_changing_confirmed_balances():
    p = Portfolio(balances={"USD": 1_000, "NVDA": 10})

    p.record_pending("0xrev", "SWAP", {"USD": -250, "NVDA": 5})
    p.discard("0xrev")

    assert p.balances == {"USD": 1_000, "NVDA": 10}
    assert "0xrev" not in p.pending


def test_discard_unknown_tx_is_a_noop():
    p = Portfolio(balances={"USD": 1_000})

    p.discard("0xmissing")

    assert p.balances == {"USD": 1_000}


def test_confirm_raises_for_unknown_tx_hash():
    p = Portfolio(balances={"USD": 1_000})

    with pytest.raises(KeyError):
        p.confirm("0xmissing")
