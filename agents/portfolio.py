from dataclasses import dataclass, field


@dataclass(frozen=True)
class PendingExecution:
    action: str
    balance_changes: dict[str, int]


@dataclass
class Portfolio:
    balances: dict[str, int] = field(default_factory=dict)
    pending: dict[str, PendingExecution] = field(default_factory=dict)

    def record_pending(self, tx_hash: str, action: str, balance_changes: dict[str, int]) -> None:
        self.pending[tx_hash] = PendingExecution(
            action=action,
            balance_changes=dict(balance_changes),
        )

    def confirm(self, tx_hash: str) -> None:
        execution = self.pending.pop(tx_hash)
        for symbol, delta in execution.balance_changes.items():
            new_balance = self.balances.get(symbol, 0) + delta
            if new_balance == 0:
                self.balances.pop(symbol, None)
            else:
                self.balances[symbol] = new_balance

    def discard(self, tx_hash: str) -> None:
        self.pending.pop(tx_hash, None)
