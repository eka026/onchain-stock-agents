import argparse
import time
from dataclasses import dataclass
from typing import Any

from agents import config
from agents.chain import (
    ChainReader,
    ChainTransactionSubmitter,
    ContractRegistry,
    ExecutionResult,
    LocalValidator,
    ReceiptVerifier,
    ValidationResult,
)
from agents.llm import LLMClient, create_llm_client
from agents.news_feed import Scenario
from agents.portfolio import Portfolio
from agents.schemas import LPDecision


@dataclass(frozen=True)
class LPRunResult:
    decision: LPDecision
    tx_hash: str | None
    execution: ExecutionResult | None
    validation: ValidationResult


class LPAgent:
    def __init__(
        self,
        *,
        lp_address: str,
        private_key: str,
        scenario: Scenario,
        reader: ChainReader,
        validator: LocalValidator,
        submitter: ChainTransactionSubmitter,
        verifier: ReceiptVerifier,
        llm_client: LLMClient,
        portfolio: Portfolio | None = None,
    ):
        self.lp_address = lp_address
        self.private_key = private_key
        self.scenario = scenario
        self.reader = reader
        self.validator = validator
        self.submitter = submitter
        self.verifier = verifier
        self.llm_client = llm_client
        self.portfolio = portfolio or Portfolio()

    def observe(self) -> dict[str, Any]:
        token_balances = {
            token.symbol: self.reader.token_balance(token.symbol, self.lp_address)
            for token in self.scenario.tokens
        }

        pools = []
        lp_balances = {}
        accumulated_fees = {}
        for pool in self.scenario.pools:
            reserve_a, reserve_b = self.reader.reserves(pool.id)
            fees_a, fees_b = self.reader.vault_fees(pool.id)
            lp_balance = self.reader.lp_balance(pool.id, self.lp_address)
            lp_total_supply = self.reader.lp_total_supply(pool.id)
            lp_symbol = _lp_symbol(pool.id)
            lp_balances[lp_symbol] = lp_balance
            accumulated_fees[pool.id] = {
                pool.base_symbol: fees_a,
                pool.quote_symbol: fees_b,
            }
            pools.append(
                {
                    **pool.model_dump(),
                    "reserve_a": reserve_a,
                    "reserve_b": reserve_b,
                    "spot_price": self.reader.spot_price(pool.id),
                    "fees_a": fees_a,
                    "fees_b": fees_b,
                    "lp_balance": lp_balance,
                    "lp_total_supply": lp_total_supply,
                    "base_balance": token_balances.get(pool.base_symbol, 0),
                    "quote_balance": token_balances.get(pool.quote_symbol, 0),
                }
            )

        policy = self.reader.lp_policy(self.lp_address)
        withdrawn_fees = self.reader.current_fee_withdrawn(self.lp_address)
        return {
            "agent_type": "lp",
            "lp_address": self.lp_address,
            "tokens": [token.model_dump() for token in self.scenario.tokens],
            "pools": pools,
            "balances": {**token_balances, **lp_balances},
            "accumulated_fees": accumulated_fees,
            "policy": {
                "enabled": policy[0],
                "max_liquidity_add": policy[1],
                "max_liquidity_remove": policy[2],
                "max_fee_withdrawal": policy[3],
                "withdrawn_fees": withdrawn_fees,
                "remaining_fee_withdrawal": max(policy[3] - withdrawn_fees, 0),
                "raw": policy,
            },
        }

    def decide(self, observation: dict[str, Any]) -> LPDecision:
        return self.llm_client.decide_lp(observation)

    def run_once(self) -> LPRunResult:
        observation = self.observe()
        decision = self.decide(observation)
        return self.execute(decision)

    def execute(self, decision: LPDecision) -> LPRunResult:
        validation = self.validator.validate_lp_decision(self.lp_address, decision)
        if not validation.ok or decision.action == "HOLD":
            return LPRunResult(
                decision=decision,
                tx_hash=None,
                execution=None,
                validation=validation,
            )

        transaction = self._build_transaction(decision)
        tx_hash = self.submitter.sign_and_submit(transaction, self.private_key)
        self.portfolio.record_pending(tx_hash, decision.action, self._planned_changes(decision))

        execution = self._verify(tx_hash, decision)
        if execution.status == "CONFIRMED":
            self.portfolio.record_pending(
                tx_hash,
                decision.action,
                self._confirmed_changes(decision, execution.event_data or {}),
            )
            self.portfolio.confirm(tx_hash)
        elif execution.status == "REJECTED":
            self.portfolio.discard(tx_hash)

        return LPRunResult(
            decision=decision,
            tx_hash=tx_hash,
            execution=execution,
            validation=validation,
        )

    def _build_transaction(self, decision: LPDecision) -> dict[str, Any]:
        if decision.action == "ADD_LIQUIDITY":
            return self.submitter.build_add_liquidity_transaction(self.lp_address, decision)
        if decision.action == "REMOVE_LIQUIDITY":
            return self.submitter.build_remove_liquidity_transaction(self.lp_address, decision)
        if decision.action == "COLLECT_FEES":
            return self.submitter.build_collect_fees_transaction(self.lp_address, decision)
        raise ValueError(f"unsupported LP action: {decision.action}")

    def _verify(self, tx_hash: str, decision: LPDecision) -> ExecutionResult:
        pool_id = decision.pool_id or ""
        if decision.action == "ADD_LIQUIDITY":
            return self.verifier.verify_add_liquidity(tx_hash, pool_id)
        if decision.action == "REMOVE_LIQUIDITY":
            return self.verifier.verify_remove_liquidity(tx_hash, pool_id)
        if decision.action == "COLLECT_FEES":
            return self.verifier.verify_collect_fees(tx_hash, pool_id)
        raise ValueError(f"unsupported LP action: {decision.action}")

    def _planned_changes(self, decision: LPDecision) -> dict[str, int]:
        pool = self.scenario_pool(decision.pool_id or "")
        lp_symbol = _lp_symbol(pool.id)
        if decision.action == "ADD_LIQUIDITY":
            return {
                pool.base_symbol: -(decision.amount_a or 0),
                pool.quote_symbol: -(decision.amount_b or 0),
                lp_symbol: 0,
            }
        if decision.action == "REMOVE_LIQUIDITY":
            return {
                pool.base_symbol: 0,
                pool.quote_symbol: 0,
                lp_symbol: -(decision.lp_shares or 0),
            }
        if decision.action == "COLLECT_FEES":
            return {
                pool.base_symbol: 0,
                pool.quote_symbol: 0,
            }
        raise ValueError(f"unsupported LP action: {decision.action}")

    def _confirmed_changes(self, decision: LPDecision, event_data: dict[str, Any]) -> dict[str, int]:
        pool = self.scenario_pool(decision.pool_id or "")
        lp_symbol = _lp_symbol(pool.id)
        if decision.action == "ADD_LIQUIDITY":
            amount_a = _event_value(event_data, "amountA", "amount_a")
            amount_b = _event_value(event_data, "amountB", "amount_b")
            lp_shares = _event_value(event_data, "lpShares", "lp_shares")
            return {
                pool.base_symbol: -int(amount_a if amount_a is not None else decision.amount_a or 0),
                pool.quote_symbol: -int(amount_b if amount_b is not None else decision.amount_b or 0),
                lp_symbol: int(lp_shares if lp_shares is not None else 0),
            }
        if decision.action == "REMOVE_LIQUIDITY":
            amount_a = _event_value(event_data, "amountA", "amount_a")
            amount_b = _event_value(event_data, "amountB", "amount_b")
            lp_shares = _event_value(event_data, "lpShares", "lp_shares")
            return {
                pool.base_symbol: int(amount_a if amount_a is not None else 0),
                pool.quote_symbol: int(amount_b if amount_b is not None else 0),
                lp_symbol: -int(lp_shares if lp_shares is not None else decision.lp_shares or 0),
            }
        if decision.action == "COLLECT_FEES":
            fees_a = _event_value(event_data, "feesA", "fees_a")
            fees_b = _event_value(event_data, "feesB", "fees_b")
            return {
                pool.base_symbol: int(fees_a if fees_a is not None else 0),
                pool.quote_symbol: int(fees_b if fees_b is not None else 0),
            }
        raise ValueError(f"unsupported LP action: {decision.action}")

    def scenario_pool(self, pool_id: str):
        for pool in self.scenario.pools:
            if pool.id == pool_id:
                return pool
        raise KeyError(f"unknown pool_id: {pool_id}")


def build_agent(index: int, *, llm_override: str | None = None) -> LPAgent:
    loaded = config.load(require_traders=False)
    lp_config = loaded.lps[index]
    registry = ContractRegistry.from_rpc(loaded.scenario, loaded.rpc_url)
    reader = ChainReader(registry)
    account = registry.web3.eth.account.from_key(lp_config.private_key)
    model = llm_override or lp_config.model
    llm_client = create_llm_client(
        model,
        openai_api_key=loaded.openai_api_key,
        google_api_key=loaded.google_api_key,
        groq_api_key=loaded.groq_api_key,
    )
    return LPAgent(
        lp_address=account.address,
        private_key=lp_config.private_key,
        scenario=loaded.scenario,
        reader=reader,
        validator=LocalValidator(reader),
        submitter=ChainTransactionSubmitter(registry),
        verifier=ReceiptVerifier(registry),
        llm_client=llm_client,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--llm", default=None)
    args = parser.parse_args(argv)

    agent = build_agent(args.index, llm_override=args.llm)

    if args.once:
        _print_result(agent.run_once())
        return 0

    while True:
        _print_result(agent.run_once())
        time.sleep(args.interval)


def _lp_symbol(pool_id: str) -> str:
    return f"{pool_id}-LP"


def _event_value(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def _print_result(result: LPRunResult) -> None:
    execution_status = result.execution.status if result.execution else None
    print(
        {
            "decision": result.decision.model_dump(),
            "validation": result.validation.ok,
            "validation_reason": result.validation.reason,
            "tx_hash": result.tx_hash,
            "execution_status": execution_status,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
