import json
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    from web3 import Web3
    from web3.exceptions import ContractLogicError, TimeExhausted, TransactionNotFound
except ModuleNotFoundError:
    class ContractLogicError(Exception):
        pass

    class TimeExhausted(Exception):
        pass

    class TransactionNotFound(Exception):
        pass

    class Web3:  # type: ignore[no-redef]
        class HTTPProvider:
            def __init__(self, *_args: Any, **_kwargs: Any):
                raise RuntimeError("web3 is required for RPC connections")

from agents.news_feed import PoolInfo, Scenario
from agents.schemas import LPDecision, TraderDecision
from utils.logger import log


DEFAULT_ABI_DIR = Path(__file__).resolve().parent / "abis"


def _is_pool_no_liquidity_error(exc: Exception) -> bool:
    return "POOL_NO_LIQUIDITY" in str(exc)


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "Too Many Requests" in text


def _rpc_with_retry(method: str, loader: Any, *, attempts: int = 3, base_delay: float = 1.0) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return loader()
        except Exception as exc:
            last_error = exc
            if not _is_rate_limit_error(exc) or attempt == attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            log({"type": "rpc_retry", "method": method, "attempt": attempt + 1, "delay_seconds": delay, "reason": str(exc)})
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"RPC retry failed without an error: {method}")


@dataclass
class PoolContracts:
    info: PoolInfo
    pool: Any
    lp_token: Any
    vault: Any
    base_token: Any
    quote_token: Any


class ContractRegistry:
    def __init__(self, scenario: Scenario, web3: Any, abi_dir: str | Path = DEFAULT_ABI_DIR):
        self.scenario = scenario
        self.web3 = web3
        self.abi_dir = Path(abi_dir)
        self.abis = {
            "AgentPolicy": self._load_abi("AgentPolicy"),
            "AMMPool": self._load_abi("AMMPool"),
            "LPToken": self._load_abi("LPToken"),
            "FeeVault": self._load_abi("FeeVault"),
            "MockERC20": self._load_abi("MockERC20"),
        }
        self.tokens_by_symbol = {token.symbol: token.address for token in scenario.tokens}
        self.pools_by_id = {pool.id: pool for pool in scenario.pools}

        self.policy = self._contract(scenario.policy_address, "AgentPolicy")
        self.tokens = {
            symbol: self._contract(address, "MockERC20")
            for symbol, address in self.tokens_by_symbol.items()
        }
        self.pools = {
            pool_id: PoolContracts(
                info=pool,
                pool=self._contract(pool.pool_address, "AMMPool"),
                lp_token=self._contract(pool.lp_token_address, "LPToken"),
                vault=self._contract(pool.vault_address, "FeeVault"),
                base_token=self.token_contract(pool.base_symbol),
                quote_token=self.token_contract(pool.quote_symbol),
            )
            for pool_id, pool in self.pools_by_id.items()
        }

    @classmethod
    def from_rpc(cls, scenario: Scenario, rpc_url: str, abi_dir: str | Path = DEFAULT_ABI_DIR) -> "ContractRegistry":
        return cls(scenario=scenario, web3=Web3(Web3.HTTPProvider(rpc_url)), abi_dir=abi_dir)

    def token_address(self, symbol: str) -> str:
        try:
            return self.tokens_by_symbol[symbol]
        except KeyError as exc:
            raise KeyError(f"unknown token symbol: {symbol}") from exc

    def token_contract(self, symbol: str) -> Any:
        try:
            return self.tokens[symbol]
        except KeyError as exc:
            raise KeyError(f"unknown token symbol: {symbol}") from exc

    def pool_info(self, pool_id: str) -> PoolInfo:
        try:
            return self.pools_by_id[pool_id]
        except KeyError as exc:
            raise KeyError(f"unknown pool_id: {pool_id}") from exc

    def pool_contracts(self, pool_id: str) -> PoolContracts:
        try:
            return self.pools[pool_id]
        except KeyError as exc:
            raise KeyError(f"unknown pool_id: {pool_id}") from exc

    def _load_abi(self, contract_name: str) -> list[dict[str, Any]]:
        path = self.abi_dir / f"{contract_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"missing ABI file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _contract(self, address: str, contract_name: str) -> Any:
        if not address:
            raise ValueError(f"missing address for {contract_name}")
        return self.web3.eth.contract(address=address, abi=self.abis[contract_name])


class ChainReader:
    def __init__(self, registry: ContractRegistry):
        self.registry = registry
        self._cache: dict[tuple[Any, ...], Any] = {}
        self._cache_enabled = False

    def enable_cache(self) -> None:
        self._cache_enabled = True

    def reset_cache(self) -> None:
        self._cache = {}
        self._cache_enabled = False

    def _cached(self, key: tuple[Any, ...], loader: Any) -> Any:
        if not self._cache_enabled:
            return loader()
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def token_balance(self, symbol: str, account: str) -> int:
        log({"type": "rpc_request", "method": "balanceOf", "symbol": symbol, "account": account})
        return _rpc_with_retry("balanceOf", lambda: self.registry.token_contract(symbol).functions.balanceOf(account).call())

    def lp_balance(self, pool_id: str, account: str) -> int:
        log({"type": "rpc_request", "method": "lp_balanceOf", "pool_id": pool_id, "account": account})
        return _rpc_with_retry("lp_balanceOf", lambda: self.registry.pool_contracts(pool_id).lp_token.functions.balanceOf(account).call())

    def lp_total_supply(self, pool_id: str) -> int:
        log({"type": "rpc_request", "method": "totalSupply", "pool_id": pool_id})
        return _rpc_with_retry("totalSupply", lambda: self.registry.pool_contracts(pool_id).lp_token.functions.totalSupply().call())

    def reserves(self, pool_id: str) -> tuple[int, int]:
        def load() -> tuple[int, int]:
            log({"type": "rpc_request", "method": "reserves", "pool_id": pool_id})
            pool = self.registry.pool_contracts(pool_id).pool
            return _rpc_with_retry(
                "reserves",
                lambda: (
                    pool.functions.reserveA().call(),
                    pool.functions.reserveB().call(),
                ),
            )

        return self._cached(("reserves", pool_id), load)

    def spot_price(self, pool_id: str) -> int:
        def load() -> int:
            log({"type": "rpc_request", "method": "spotPrice", "pool_id": pool_id})
            try:
                return _rpc_with_retry("spotPrice", lambda: self.registry.pool_contracts(pool_id).pool.functions.spotPrice().call())
            except ContractLogicError as exc:
                if _is_pool_no_liquidity_error(exc):
                    log({"type": "rpc_response", "method": "spotPrice", "pool_id": pool_id, "status": "POOL_NO_LIQUIDITY"})
                    return 0
                raise

        return self._cached(("spot_price", pool_id), load)

    def vault_fees(self, pool_id: str) -> tuple[int, int]:
        def load() -> tuple[int, int]:
            log({"type": "rpc_request", "method": "vault_fees", "pool_id": pool_id})
            vault = self.registry.pool_contracts(pool_id).vault
            return _rpc_with_retry(
                "vault_fees",
                lambda: (
                    vault.functions.totalFeesA().call(),
                    vault.functions.totalFeesB().call(),
                ),
            )

        return self._cached(("vault_fees", pool_id), load)

    def vault_cumulative_fees(self, pool_id: str) -> tuple[int, int]:
        def load() -> tuple[int, int]:
            log({"type": "rpc_request", "method": "vault_cumulative_fees", "pool_id": pool_id})
            vault = self.registry.pool_contracts(pool_id).vault
            return _rpc_with_retry(
                "vault_cumulative_fees",
                lambda: (
                    vault.functions.cumulativeFeesA().call(),
                    vault.functions.cumulativeFeesB().call(),
                ),
            )

        return self._cached(("vault_cumulative_fees", pool_id), load)

    def claimable_fees(self, pool_id: str, lp: str, lp_shares: int) -> tuple[int, int]:
        def load() -> tuple[int, int]:
            log({"type": "rpc_request", "method": "claimableFees", "pool_id": pool_id, "lp": lp, "lp_shares": lp_shares})
            vault = self.registry.pool_contracts(pool_id).vault
            return _rpc_with_retry("claimableFees", lambda: tuple(vault.functions.claimableFees(lp, lp_shares).call()))

        return self._cached(("claimable_fees", pool_id, lp, lp_shares), load)

    def pool_fee_bps(self, pool_id: str) -> int:
        def load() -> int:
            log({"type": "rpc_request", "method": "feeBps", "pool_id": pool_id})
            return _rpc_with_retry("feeBps", lambda: self.registry.pool_contracts(pool_id).pool.functions.feeBps().call())

        return self._cached(("pool_fee_bps", pool_id), load)

    def is_token_approved(self, symbol: str) -> bool:
        def load() -> bool:
            log({"type": "rpc_request", "method": "isTokenApproved", "symbol": symbol})
            address = self.registry.token_address(symbol)
            return _rpc_with_retry("isTokenApproved", lambda: self.registry.policy.functions.isTokenApproved(address).call())

        return self._cached(("is_token_approved", symbol), load)

    def trader_policy(self, trader: str) -> Any:
        log({"type": "rpc_request", "method": "traderPolicies", "trader": trader})
        return _rpc_with_retry("traderPolicies", lambda: self.registry.policy.functions.traderPolicies(trader).call())

    def lp_policy(self, lp: str) -> Any:
        log({"type": "rpc_request", "method": "lpPolicies", "lp": lp})
        return _rpc_with_retry("lpPolicies", lambda: self.registry.policy.functions.lpPolicies(lp).call())

    def current_spent_amount(self, trader: str) -> int:
        log({"type": "rpc_request", "method": "currentSpentAmount", "trader": trader})
        return _rpc_with_retry("currentSpentAmount", lambda: self.registry.policy.functions.currentSpentAmount(trader).call())

    def current_fee_withdrawn(self, lp: str) -> int:
        log({"type": "rpc_request", "method": "currentFeeWithdrawn", "lp": lp})
        return _rpc_with_retry("currentFeeWithdrawn", lambda: self.registry.policy.functions.currentFeeWithdrawn(lp).call())

    def spot_price_history(self, pool_id: str) -> list[int]:
        """
        Returns spotPrice() sampled at the block of every Swap event, preceded by
        the price at the first LiquidityAdded block so the chart starts from pool
        inception rather than the first trade.  Falls back to [current_price] if
        the node doesn't support historical calls or has no events.
        """
        pool = self.registry.pool_contracts(pool_id).pool
        blocks: list[int] = []

        # Anchor the start at the first liquidity provision so the chart begins
        # at the initial price, not the first swap.
        try:
            liq_logs = pool.events.LiquidityAdded.get_logs(fromBlock=0)
            if liq_logs:
                blocks.append(min(log["blockNumber"] for log in liq_logs))
        except Exception:
            pass

        from_block = blocks[0] if blocks else 0

        try:
            swap_logs = pool.events.Swap.get_logs(fromBlock=from_block)
            for log in swap_logs:
                blocks.append(log["blockNumber"])
        except Exception:
            pass

        if not blocks:
            return [self.spot_price(pool_id)]

        prices: list[int] = []
        seen: set[int] = set()
        for bn in sorted(blocks):
            if bn in seen:
                continue
            seen.add(bn)
            try:
                price = pool.functions.spotPrice().call(block_identifier=bn)
                prices.append(price)
            except Exception:
                continue

        current = self.spot_price(pool_id)
        if not prices or prices[-1] != current:
            prices.append(current)

        return prices if prices else [current]

    def token_allowance(self, symbol: str, owner: str, spender: str) -> int:
        log({"type": "rpc_request", "method": "allowance", "symbol": symbol, "owner": owner, "spender": spender})
        return _rpc_with_retry("allowance", lambda: self.registry.token_contract(symbol).functions.allowance(owner, spender).call())


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str | None = None


class LocalValidator:
    def __init__(self, reader: ChainReader):
        self.reader = reader
        self.registry = reader.registry

    def validate_trader_decision(self, trader: str, decision: TraderDecision) -> ValidationResult:
        if decision.action == "HOLD":
            return ValidationResult(ok=True)

        pool_result = self._validate_pool(decision.pool_id)
        if not pool_result.ok:
            return pool_result

        pool = self.registry.pool_info(decision.pool_id or "")
        if decision.token_in not in pool.symbols():
            expected = ", ".join(sorted(pool.symbols()))
            return ValidationResult(ok=False, reason=f"token_in must be one of {expected}")

        if decision.amount_in is None or decision.amount_in <= 0:
            return ValidationResult(ok=False, reason="amount_in must be positive")

        try:
            reserve_a, reserve_b = self.reader.reserves(pool.id)
            if reserve_a <= 0 or reserve_b <= 0:
                return ValidationResult(ok=False, reason="pool has no liquidity")
        except Exception:
            pass

        if not self.reader.is_token_approved(decision.token_in or ""):
            return ValidationResult(ok=False, reason="token is not approved")

        policy = self.reader.trader_policy(trader)
        enabled, max_swap_amount, spending_limit = policy[:3]
        spent_amount = self.reader.current_spent_amount(trader)
        if not enabled:
            return ValidationResult(ok=False, reason="trader policy is disabled")
        if decision.amount_in > max_swap_amount:
            return ValidationResult(ok=False, reason="swap exceeds max swap amount")
        if spent_amount + decision.amount_in > spending_limit:
            return ValidationResult(ok=False, reason="swap exceeds spending limit")

        pool_address = self.registry.pool_contracts(pool.id).info.pool_address
        allowance = self.reader.token_allowance(decision.token_in or "", trader, pool_address)
        if allowance < decision.amount_in:
            return ValidationResult(ok=False, reason="insufficient token allowance")

        return ValidationResult(ok=True)

    def validate_lp_decision(self, lp: str, decision: LPDecision) -> ValidationResult:
        if decision.action == "HOLD":
            return ValidationResult(ok=True)

        pool_result = self._validate_pool(decision.pool_id)
        if not pool_result.ok:
            return pool_result

        pool = self.registry.pool_info(decision.pool_id or "")
        contracts = self.registry.pool_contracts(pool.id)
        policy = self.reader.lp_policy(lp)
        enabled, max_liquidity_add, max_liquidity_remove, max_fee_withdrawal = policy[:4]
        withdrawn_fees = self.reader.current_fee_withdrawn(lp)
        if not enabled:
            return ValidationResult(ok=False, reason="LP policy is disabled")

        if decision.action == "ADD_LIQUIDITY":
            if decision.amount_a is None or decision.amount_a <= 0:
                return ValidationResult(ok=False, reason="amount_a must be positive")
            if decision.amount_b is None or decision.amount_b <= 0:
                return ValidationResult(ok=False, reason="amount_b must be positive")
            if decision.amount_a > max_liquidity_add or decision.amount_b > max_liquidity_add:
                return ValidationResult(ok=False, reason="liquidity add exceeds policy limit")

            base_allowance = self.reader.token_allowance(pool.base_symbol, lp, contracts.info.pool_address)
            quote_allowance = self.reader.token_allowance(pool.quote_symbol, lp, contracts.info.pool_address)
            if base_allowance < decision.amount_a:
                return ValidationResult(ok=False, reason="insufficient base token allowance")
            if quote_allowance < decision.amount_b:
                return ValidationResult(ok=False, reason="insufficient quote token allowance")

        if decision.action == "REMOVE_LIQUIDITY":
            if decision.lp_shares is None or decision.lp_shares <= 0:
                return ValidationResult(ok=False, reason="lp_shares must be positive")
            if decision.lp_shares > max_liquidity_remove:
                return ValidationResult(ok=False, reason="liquidity remove exceeds policy limit")

        if decision.action == "COLLECT_FEES":
            if decision.lp_shares is None or decision.lp_shares <= 0:
                return ValidationResult(ok=False, reason="lp_shares must be positive")
            total_supply = self.reader.lp_total_supply(pool.id)
            if total_supply <= 0:
                return ValidationResult(ok=False, reason="LP token supply is zero")
            fees_a, fees_b = self.reader.claimable_fees(pool.id, lp, decision.lp_shares)
            fee_amount = fees_a + fees_b
            if withdrawn_fees + fee_amount > max_fee_withdrawal:
                return ValidationResult(ok=False, reason="fee withdrawal exceeds policy limit")

        return ValidationResult(ok=True)

    def _validate_pool(self, pool_id: str | None) -> ValidationResult:
        if not pool_id:
            return ValidationResult(ok=False, reason="pool_id is required")
        try:
            self.registry.pool_info(pool_id)
        except KeyError:
            return ValidationResult(ok=False, reason=f"unknown pool_id: {pool_id}")
        return ValidationResult(ok=True)


ExecutionStatus = Literal["CONFIRMED", "REJECTED", "PENDING"]


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    tx_hash: str
    action: str
    pool_id: str | None = None
    event_name: str | None = None
    event_data: dict[str, Any] | None = None
    receipt: Any | None = None
    reason: str | None = None


class ChainTransactionSubmitter:
    def __init__(
        self,
        registry: ContractRegistry,
        *,
        default_gas: int = 500_000,
        default_gas_price: int | None = None,
        default_deadline_seconds: int = 300,
    ):
        self.registry = registry
        self.web3 = registry.web3
        self.default_gas = default_gas
        self.default_gas_price = default_gas_price
        self.default_deadline_seconds = default_deadline_seconds

    def build_swap_transaction(
        self,
        trader: str,
        decision: TraderDecision,
        *,
        min_amount_out: int | None = None,
        deadline: int | None = None,
        tx_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log({"type": "rpc_request", "method": "build_swap", "trader": trader, "pool_id": decision.pool_id, "token_in": decision.token_in, "amount_in": decision.amount_in, "min_amount_out": min_amount_out})
        if decision.action != "SWAP":
            raise ValueError("build_swap_transaction requires a SWAP decision")
        if decision.max_slippage_bps is not None and min_amount_out is None:
            raise ValueError("min_amount_out is required when max_slippage_bps is set")
        pool = self.registry.pool_contracts(decision.pool_id or "")
        token_in = self.registry.token_address(decision.token_in or "")
        resolved_deadline = deadline if deadline is not None else self._deadline(decision.deadline_seconds)
        function = pool.pool.functions.swap(
            token_in,
            decision.amount_in,
            min_amount_out if min_amount_out is not None else 0,
            resolved_deadline,
        )
        return function.build_transaction(self._tx_params(trader, tx_options))

    def build_add_liquidity_transaction(
        self,
        lp: str,
        decision: LPDecision,
        *,
        tx_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log({"type": "rpc_request", "method": "build_add_liquidity", "lp": lp, "pool_id": decision.pool_id, "amount_a": decision.amount_a, "amount_b": decision.amount_b})
        if decision.action != "ADD_LIQUIDITY":
            raise ValueError("build_add_liquidity_transaction requires an ADD_LIQUIDITY decision")
        pool = self.registry.pool_contracts(decision.pool_id or "")
        function = pool.pool.functions.addLiquidity(
            decision.amount_a,
            decision.amount_b,
            decision.min_lp_shares if decision.min_lp_shares is not None else 0,
        )
        return function.build_transaction(self._tx_params(lp, tx_options))

    def build_remove_liquidity_transaction(
        self,
        lp: str,
        decision: LPDecision,
        *,
        tx_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log({"type": "rpc_request", "method": "build_remove_liquidity", "lp": lp, "pool_id": decision.pool_id, "lp_shares": decision.lp_shares})
        if decision.action != "REMOVE_LIQUIDITY":
            raise ValueError("build_remove_liquidity_transaction requires a REMOVE_LIQUIDITY decision")
        pool = self.registry.pool_contracts(decision.pool_id or "")
        function = pool.pool.functions.removeLiquidity(decision.lp_shares)
        return function.build_transaction(self._tx_params(lp, tx_options))

    def build_collect_fees_transaction(
        self,
        lp: str,
        decision: LPDecision,
        *,
        tx_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log({"type": "rpc_request", "method": "build_collect_fees", "lp": lp, "pool_id": decision.pool_id, "lp_shares": decision.lp_shares})
        if decision.action != "COLLECT_FEES":
            raise ValueError("build_collect_fees_transaction requires a COLLECT_FEES decision")
        vault = self.registry.pool_contracts(decision.pool_id or "").vault
        function = vault.functions.collectFees(decision.lp_shares)
        return function.build_transaction(self._tx_params(lp, tx_options))

    def sign_transaction(self, transaction: dict[str, Any], private_key: str) -> Any:
        return self.web3.eth.account.sign_transaction(transaction, private_key)

    def submit_signed_transaction(self, signed_transaction: Any) -> str:
        raw_transaction = getattr(signed_transaction, "rawTransaction", None)
        if raw_transaction is None:
            raw_transaction = getattr(signed_transaction, "raw_transaction")
        tx_hash = _rpc_with_retry("send_raw_transaction", lambda: self.web3.eth.send_raw_transaction(raw_transaction))
        log({"type": "rpc_response", "method": "send_raw_transaction", "tx_hash": self._hex(tx_hash)})
        return self._hex(tx_hash)

    def sign_and_submit(self, transaction: dict[str, Any], private_key: str) -> str:
        return self.submit_signed_transaction(self.sign_transaction(transaction, private_key))

    def submit_trader_decision(self, trader: str, private_key: str, decision: TraderDecision) -> str | None:
        if decision.action == "HOLD":
            return None
        return self.sign_and_submit(self.build_swap_transaction(trader, decision), private_key)

    def submit_lp_decision(self, lp: str, private_key: str, decision: LPDecision) -> str | None:
        if decision.action == "HOLD":
            return None
        if decision.action == "ADD_LIQUIDITY":
            transaction = self.build_add_liquidity_transaction(lp, decision)
        elif decision.action == "REMOVE_LIQUIDITY":
            transaction = self.build_remove_liquidity_transaction(lp, decision)
        elif decision.action == "COLLECT_FEES":
            transaction = self.build_collect_fees_transaction(lp, decision)
        else:
            raise ValueError(f"unsupported LP action: {decision.action}")
        return self.sign_and_submit(transaction, private_key)

    def _tx_params(self, sender: str, tx_options: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {
            "from": sender,
            "nonce": _rpc_with_retry("get_transaction_count", lambda: self.web3.eth.get_transaction_count(sender)),
            "gas": self.default_gas,
        }
        chain_id = _rpc_with_retry("chain_id", lambda: getattr(self.web3.eth, "chain_id", None))
        if chain_id is not None:
            params["chainId"] = chain_id
        gas_price = self.default_gas_price
        if gas_price is None and hasattr(self.web3.eth, "gas_price"):
            gas_price = _rpc_with_retry("gas_price", lambda: self.web3.eth.gas_price)
        if gas_price is not None:
            params["gasPrice"] = gas_price
        if tx_options:
            params.update(tx_options)
        return params

    def _deadline(self, deadline_seconds: int | None) -> int:
        seconds = deadline_seconds or self.default_deadline_seconds
        wall_clock_timestamp = int(time.time())
        try:
            latest_block = _rpc_with_retry("get_block", lambda: self.web3.eth.get_block("latest"))
            chain_timestamp = latest_block["timestamp"] if isinstance(latest_block, dict) else latest_block.timestamp
        except Exception:
            chain_timestamp = wall_clock_timestamp
        timestamp = max(int(chain_timestamp), wall_clock_timestamp)
        return int(timestamp) + seconds

    def _hex(self, value: Any) -> str:
        if isinstance(value, bytes):
            hex_str = value.hex()
            return hex_str if hex_str.startswith("0x") else "0x" + hex_str
        if hasattr(value, "hex"):
            return value.hex()
        return str(value)


class ReceiptVerifier:
    EVENT_CONTRACTS = {
        "Swap": "pool",
        "LiquidityAdded": "pool",
        "LiquidityRemoved": "pool",
        "FeesCollected": "vault",
    }

    def __init__(self, registry: ContractRegistry):
        self.registry = registry
        self.web3 = registry.web3

    def verify(
        self,
        tx_hash: str,
        *,
        action: str,
        pool_id: str,
        expected_event: str,
        timeout: int = 120,
        poll_latency: int = 2,
    ) -> ExecutionResult:
        receipt = self._receipt(tx_hash, timeout=timeout, poll_latency=poll_latency)
        log({"type": "rpc_response", "method": "wait_for_receipt", "tx_hash": tx_hash, "status": self._receipt_status(receipt) if receipt is not None else None})
        if receipt is None:
            log({"type": "execution_result", "status": "PENDING", "tx_hash": tx_hash, "action": action, "reason": "receipt unavailable"})
            return ExecutionResult(
                status="PENDING",
                tx_hash=tx_hash,
                action=action,
                pool_id=pool_id,
                event_name=expected_event,
                reason="receipt unavailable",
            )

        receipt_status = self._receipt_status(receipt)
        if receipt_status is None:
            log({"type": "execution_result", "status": "REJECTED", "tx_hash": tx_hash, "action": action, "reason": "receipt missing status"})
            return ExecutionResult(
                status="REJECTED",
                tx_hash=tx_hash,
                action=action,
                pool_id=pool_id,
                event_name=expected_event,
                receipt=receipt,
                reason="receipt missing status",
            )

        if receipt_status == 0:
            log({"type": "execution_result", "status": "REJECTED", "tx_hash": tx_hash, "action": action, "reason": "transaction reverted"})
            return ExecutionResult(
                status="REJECTED",
                tx_hash=tx_hash,
                action=action,
                pool_id=pool_id,
                event_name=expected_event,
                receipt=receipt,
                reason="transaction reverted",
            )

        event_data = self._extract_event(pool_id, expected_event, receipt)
        if event_data is None:
            log({"type": "execution_result", "status": "REJECTED", "tx_hash": tx_hash, "action": action, "reason": f"missing expected event: {expected_event}"})
            return ExecutionResult(
                status="REJECTED",
                tx_hash=tx_hash,
                action=action,
                pool_id=pool_id,
                event_name=expected_event,
                receipt=receipt,
                reason=f"missing expected event: {expected_event}",
            )

        log({"type": "execution_result", "status": "CONFIRMED", "tx_hash": tx_hash, "action": action, "pool_id": pool_id, "event_name": expected_event, "event_data": event_data})
        return ExecutionResult(
            status="CONFIRMED",
            tx_hash=tx_hash,
            action=action,
            pool_id=pool_id,
            event_name=expected_event,
            event_data=event_data,
            receipt=receipt,
        )

    def verify_swap(self, tx_hash: str, pool_id: str, *, timeout: int = 120) -> ExecutionResult:
        return self.verify(tx_hash, action="SWAP", pool_id=pool_id, expected_event="Swap", timeout=timeout)

    def verify_add_liquidity(self, tx_hash: str, pool_id: str, *, timeout: int = 120) -> ExecutionResult:
        return self.verify(
            tx_hash,
            action="ADD_LIQUIDITY",
            pool_id=pool_id,
            expected_event="LiquidityAdded",
            timeout=timeout,
        )

    def verify_remove_liquidity(self, tx_hash: str, pool_id: str, *, timeout: int = 120) -> ExecutionResult:
        return self.verify(
            tx_hash,
            action="REMOVE_LIQUIDITY",
            pool_id=pool_id,
            expected_event="LiquidityRemoved",
            timeout=timeout,
        )

    def verify_collect_fees(self, tx_hash: str, pool_id: str, *, timeout: int = 120) -> ExecutionResult:
        return self.verify(
            tx_hash,
            action="COLLECT_FEES",
            pool_id=pool_id,
            expected_event="FeesCollected",
            timeout=timeout,
        )

    def _receipt(self, tx_hash: str, *, timeout: int, poll_latency: int) -> Any | None:
        try:
            return _rpc_with_retry(
                "wait_for_transaction_receipt",
                lambda: self.web3.eth.wait_for_transaction_receipt(
                    tx_hash,
                    timeout=timeout,
                    poll_latency=poll_latency,
                ),
            )
        except (TimeExhausted, TransactionNotFound):
            return None

    def _receipt_status(self, receipt: Any) -> int | None:
        if isinstance(receipt, dict):
            return receipt.get("status")
        return getattr(receipt, "status", None)

    def _extract_event(self, pool_id: str, event_name: str, receipt: Any) -> dict[str, Any] | None:
        pool_contracts = self.registry.pool_contracts(pool_id)
        contract_name = self.EVENT_CONTRACTS.get(event_name)
        if contract_name is None:
            raise ValueError(f"unsupported expected event: {event_name}")
        contract = getattr(pool_contracts, contract_name)
        event = getattr(contract.events, event_name)()
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*MismatchedABI.*",
                category=UserWarning,
                module=r"web3\.contract\.base_contract",
            )
            logs = event.process_receipt(receipt)
        if not logs:
            return None
        # Contract methods used here emit one action event; take the first matching log.
        first_log = logs[0]
        if isinstance(first_log, dict):
            args = first_log.get("args", first_log)
        else:
            args = getattr(first_log, "args", first_log)
        return dict(args)
