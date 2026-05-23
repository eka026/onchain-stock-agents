import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    from web3 import Web3
    from web3.exceptions import TimeExhausted, TransactionNotFound
except ModuleNotFoundError:
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


DEFAULT_ABI_DIR = Path(__file__).resolve().parent / "abis"


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

    def token_balance(self, symbol: str, account: str) -> int:
        return self.registry.token_contract(symbol).functions.balanceOf(account).call()

    def lp_balance(self, pool_id: str, account: str) -> int:
        return self.registry.pool_contracts(pool_id).lp_token.functions.balanceOf(account).call()

    def lp_total_supply(self, pool_id: str) -> int:
        return self.registry.pool_contracts(pool_id).lp_token.functions.totalSupply().call()

    def reserves(self, pool_id: str) -> tuple[int, int]:
        pool = self.registry.pool_contracts(pool_id).pool
        return (
            pool.functions.reserveA().call(),
            pool.functions.reserveB().call(),
        )

    def spot_price(self, pool_id: str) -> int:
        return self.registry.pool_contracts(pool_id).pool.functions.spotPrice().call()

    def vault_fees(self, pool_id: str) -> tuple[int, int]:
        vault = self.registry.pool_contracts(pool_id).vault
        return (
            vault.functions.totalFeesA().call(),
            vault.functions.totalFeesB().call(),
        )

    def is_token_approved(self, symbol: str) -> bool:
        address = self.registry.token_address(symbol)
        return self.registry.policy.functions.isTokenApproved(address).call()

    def trader_policy(self, trader: str) -> Any:
        return self.registry.policy.functions.traderPolicies(trader).call()

    def lp_policy(self, lp: str) -> Any:
        return self.registry.policy.functions.lpPolicies(lp).call()

    def current_spent_amount(self, trader: str) -> int:
        return self.registry.policy.functions.currentSpentAmount(trader).call()

    def current_fee_withdrawn(self, lp: str) -> int:
        return self.registry.policy.functions.currentFeeWithdrawn(lp).call()

    def token_allowance(self, symbol: str, owner: str, spender: str) -> int:
        return self.registry.token_contract(symbol).functions.allowance(owner, spender).call()


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

        if not self.reader.is_token_approved(decision.token_in or ""):
            return ValidationResult(ok=False, reason="token is not approved")

        pool_address = self.registry.pool_contracts(pool.id).info.pool_address
        allowance = self.reader.token_allowance(decision.token_in or "", trader, pool_address)
        if allowance < decision.amount_in:
            return ValidationResult(ok=False, reason="insufficient token allowance")

        policy = self.reader.trader_policy(trader)
        enabled, max_swap_amount, spending_limit = policy[:3]
        spent_amount = self.reader.current_spent_amount(trader)
        if not enabled:
            return ValidationResult(ok=False, reason="trader policy is disabled")
        if decision.amount_in > max_swap_amount:
            return ValidationResult(ok=False, reason="swap exceeds max swap amount")
        if spent_amount + decision.amount_in > spending_limit:
            return ValidationResult(ok=False, reason="swap exceeds spending limit")

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
            fees_a, fees_b = self.reader.vault_fees(pool.id)
            total_supply = self.reader.lp_total_supply(pool.id)
            if total_supply <= 0:
                return ValidationResult(ok=False, reason="LP token supply is zero")
            fee_amount = decision.lp_shares * (fees_a + fees_b) // total_supply
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
        tx_hash = self.web3.eth.send_raw_transaction(raw_transaction)
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
            "nonce": self.web3.eth.get_transaction_count(sender),
            "gas": self.default_gas,
        }
        chain_id = getattr(self.web3.eth, "chain_id", None)
        if chain_id is not None:
            params["chainId"] = chain_id
        gas_price = self.default_gas_price
        if gas_price is None and hasattr(self.web3.eth, "gas_price"):
            gas_price = self.web3.eth.gas_price
        if gas_price is not None:
            params["gasPrice"] = gas_price
        if tx_options:
            params.update(tx_options)
        return params

    def _deadline(self, deadline_seconds: int | None) -> int:
        seconds = deadline_seconds or self.default_deadline_seconds
        try:
            latest_block = self.web3.eth.get_block("latest")
            timestamp = latest_block["timestamp"] if isinstance(latest_block, dict) else latest_block.timestamp
        except Exception:
            timestamp = int(time.time())
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
        if receipt is None:
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
            return ExecutionResult(
                status="REJECTED",
                tx_hash=tx_hash,
                action=action,
                pool_id=pool_id,
                event_name=expected_event,
                receipt=receipt,
                reason=f"missing expected event: {expected_event}",
            )

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
            return self.web3.eth.wait_for_transaction_receipt(
                tx_hash,
                timeout=timeout,
                poll_latency=poll_latency,
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
