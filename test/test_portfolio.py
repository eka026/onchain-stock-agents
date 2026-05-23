from agents.portfolio import Portfolio, PendingTrade


def test_pending_does_not_mutate_confirmed_state():
    p = Portfolio(cash=1_000, holdings={"ACME": 10})
    p.record_pending("0xabc", "BUY", "ACME", 5, 250)
    assert p.cash == 1_000
    assert p.holdings["ACME"] == 10


def test_confirmed_buy_decreases_cash_and_increases_holdings():
    p = Portfolio(cash=1_000)
    p.record_pending("0xabc", "BUY", "ACME", 5, 250)
    p.confirm("0xabc")
    assert p.cash == 750
    assert p.holdings["ACME"] == 5
    assert "0xabc" not in p.pending


def test_confirmed_sell_increases_cash_and_decreases_holdings():
    p = Portfolio(cash=500, holdings={"ACME": 10})
    p.record_pending("0xdef", "SELL", "ACME", 4, 200)
    p.confirm("0xdef")
    assert p.cash == 700
    assert p.holdings["ACME"] == 6
    assert "0xdef" not in p.pending


def test_discard_removes_pending_without_changing_confirmed_state():
    p = Portfolio(cash=1_000, holdings={"ACME": 10})
    p.record_pending("0xrev", "BUY", "ACME", 5, 250)
    p.discard("0xrev")
    assert p.cash == 1_000
    assert p.holdings["ACME"] == 10
    assert "0xrev" not in p.pending


def test_discard_unknown_tx_is_a_noop():
    p = Portfolio(cash=1_000)
    p.discard("0xnotexist")
    assert p.cash == 1_000


def test_selling_all_shares_removes_symbol_from_holdings():
    p = Portfolio(cash=0, holdings={"ACME": 5})
    p.record_pending("0xfull", "SELL", "ACME", 5, 500)
    p.confirm("0xfull")
    assert "ACME" not in p.holdings
    assert p.cash == 500


def test_buy_new_symbol_creates_holdings_entry():
    p = Portfolio(cash=500)
    p.record_pending("0xnew", "BUY", "NEWY", 10, 100)
    p.confirm("0xnew")
    assert p.holdings["NEWY"] == 10
    assert p.cash == 400


def test_multiple_pending_trades_are_independent():
    p = Portfolio(cash=1_000, holdings={"ACME": 10})
    p.record_pending("0x1", "BUY", "ACME", 3, 150)
    p.record_pending("0x2", "SELL", "ACME", 2, 100)
    p.discard("0x1")
    p.confirm("0x2")
    assert p.cash == 1_100
    assert p.holdings["ACME"] == 8
    assert not p.pending


def test_confirm_raises_for_unknown_tx_hash():
    p = Portfolio(cash=1_000)
    try:
        p.confirm("0xmissing")
        assert False, "expected KeyError"
    except KeyError:
        pass
