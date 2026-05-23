from dataclasses import dataclass, field


@dataclass
class PendingTrade:
    side: str      # "BUY" or "SELL"
    symbol: str
    shares: int
    payment: int


@dataclass
class Portfolio:
    cash: int
    holdings: dict[str, int] = field(default_factory=dict)
    pending: dict[str, PendingTrade] = field(default_factory=dict)

    def record_pending(self, tx_hash: str, side: str, symbol: str, shares: int, payment: int) -> None:
        self.pending[tx_hash] = PendingTrade(side=side, symbol=symbol, shares=shares, payment=payment)

    def confirm(self, tx_hash: str) -> None:
        trade = self.pending.pop(tx_hash)
        if trade.side == "BUY":
            self.cash -= trade.payment
            self.holdings[trade.symbol] = self.holdings.get(trade.symbol, 0) + trade.shares
        elif trade.side == "SELL":
            self.cash += trade.payment
            self.holdings[trade.symbol] = self.holdings.get(trade.symbol, 0) - trade.shares
            if self.holdings[trade.symbol] == 0:
                del self.holdings[trade.symbol]

    def discard(self, tx_hash: str) -> None:
        self.pending.pop(tx_hash, None)
