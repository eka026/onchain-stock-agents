import argparse
import time
from dataclasses import dataclass, field
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
from agents.llm import LLMClient, LLMDecisionError, create_llm_client, load_persona
from utils.logger import log
from agents.news_feed import NewsFeed, NewsItem, Scenario
from agents.portfolio import Portfolio
from agents.schemas import TraderDecision


ONE = 10**18


@dataclass(frozen=True)
class TraderRunResult:
    decision: TraderDecision
    tx_hash: str | None
    execution: ExecutionResult | None
    validation: ValidationResult


class TraderAgent:
    def __init__(
        self,
        *,
        trader_address: str,
        private_key: str,
        scenario: Scenario,
        reader: ChainReader,
        validator: LocalValidator,
        submitter: ChainTransactionSubmitter,
        verifier: ReceiptVerifier,
        llm_client: LLMClient,
        portfolio: Portfolio | None = None,
        price_history: dict[str, list[int]] | None = None,
    ):
        self.trader_address = trader_address
        self.private_key = private_key
        self.scenario = scenario
        self.reader = reader
        self.validator = validator
        self.submitter = submitter
        self.verifier = verifier
        self.llm_client = llm_client
        self.portfolio = portfolio or Portfolio()
        self.price_history: dict[str, list[int]] = price_history if price_history is not None else {}

    def observe(self, news: NewsItem | dict[str, Any] | None = None) -> dict[str, Any]:
        token_balances = {
            token.symbol: self.reader.token_balance(token.symbol, self.trader_address)
            for token in self.scenario.tokens
        }
        pools = []
        for pool in self.scenario.pools:
            reserve_a, reserve_b = self.reader.reserves(pool.id)
            spot_price = self.reader.spot_price(pool.id)
            self.price_history.setdefault(pool.base_symbol, []).append(spot_price)
            pools.append(
                {
                    **pool.model_dump(),
                    "reserve_a": reserve_a,
                    "reserve_b": reserve_b,
                    "spot_price": spot_price,
                    "fee_bps": self.reader.pool_fee_bps(pool.id),
                    "base_balance": token_balances.get(pool.base_symbol, 0),
                    "quote_balance": token_balances.get(pool.quote_symbol, 0),
                    "base_approved": self.reader.is_token_approved(pool.base_symbol),
                    "quote_approved": self.reader.is_token_approved(pool.quote_symbol),
                }
            )

        policy = self.reader.trader_policy(self.trader_address)
        spent_amount = self.reader.current_spent_amount(self.trader_address)
        return {
            "agent_type": "trader",
            "trader_address": self.trader_address,
            "news": _serialize_news(news),
            "tokens": [token.model_dump() for token in self.scenario.tokens],
            "pools": pools,
            "balances": token_balances,
            "per_token_history": dict(self.price_history),
            "policy": {
                "enabled": policy[0],
                "max_swap_amount": policy[1],
                "spending_limit": policy[2],
                "spent_amount": spent_amount,
                "remaining_spending": max(policy[2] - spent_amount, 0),
                "raw": policy,
            },
        }

    def decide(self, observation: dict[str, Any]) -> TraderDecision:
        return self.llm_client.decide_trader(observation)

    def run_once(self, news: NewsItem | dict[str, Any] | None = None) -> TraderRunResult:
        log({"type": "news_event", "agent": "trader", "trader_address": self.trader_address, "news": _serialize_news(news)})
        observation = self.observe(news)
        log({"type": "observation", "agent": "trader", "trader_address": self.trader_address, "pools": [p.get("id") for p in observation.get("pools", [])]})
        try:
            decision = self.decide(observation)
            log({"type": "decision", "agent": "trader", "action": decision.action, "pool_id": decision.pool_id, "token_in": decision.token_in, "amount_in": decision.amount_in, "reason": decision.reason})
        except LLMDecisionError as exc:
            log({"type": "error", "method": "decide_trader", "trader_address": self.trader_address, "error": str(exc)})
            return TraderRunResult(
                decision=TraderDecision(action="HOLD", reason=str(exc)),
                tx_hash=None,
                execution=None,
                validation=ValidationResult(ok=False, reason=str(exc)),
            )
        return self.execute(decision)

    def execute(self, decision: TraderDecision) -> TraderRunResult:
        validation = self.validator.validate_trader_decision(self.trader_address, decision)
        log({"type": "validation", "agent": "trader", "action": decision.action, "ok": validation.ok, "reason": validation.reason})
        if not validation.ok or decision.action == "HOLD":
            log({"type": "action", "action": decision.action, "trader": self.trader_address, "pool_id": decision.pool_id, "validation_ok": validation.ok, "reason": decision.reason or validation.reason})
            return TraderRunResult(
                decision=decision,
                tx_hash=None,
                execution=None,
                validation=validation,
            )

        min_amount_out = self._min_amount_out(decision)
        transaction = self.submitter.build_swap_transaction(
            self.trader_address,
            decision,
            min_amount_out=min_amount_out,
        )
        tx_hash = self.submitter.sign_and_submit(transaction, self.private_key)
        log({"type": "action", "action": "SWAP", "trader": self.trader_address, "pool_id": decision.pool_id, "token_in": decision.token_in, "amount_in": decision.amount_in, "tx_hash": tx_hash})

        execution = self.verifier.verify_swap(tx_hash, decision.pool_id or "")
        log({"type": "execution_result", "action": "SWAP", "trader": self.trader_address, "tx_hash": tx_hash, "status": execution.status, "event_data": execution.event_data, "reason": execution.reason})
        if execution.status == "CONFIRMED":
            confirmed_changes = self._confirmed_swap_changes(decision, execution.event_data or {})
            self.portfolio.record_pending(tx_hash, "SWAP", confirmed_changes)
            self.portfolio.confirm(tx_hash)
        elif execution.status == "REJECTED":
            self.portfolio.discard(tx_hash)
        else:
            self.portfolio.record_pending(tx_hash, "SWAP", self._planned_swap_changes(decision))

        return TraderRunResult(
            decision=decision,
            tx_hash=tx_hash,
            execution=execution,
            validation=validation,
        )

    def _min_amount_out(self, decision: TraderDecision) -> int:
        if decision.max_slippage_bps is None:
            return 0

        pool = self.scenario_pool(decision.pool_id or "")
        reserve_a, reserve_b = self.reader.reserves(pool.id)
        fee_bps = self.reader.pool_fee_bps(pool.id)
        amount_in_less_fee = (decision.amount_in or 0) * (10_000 - fee_bps) // 10_000
        if decision.token_in == pool.base_symbol:
            reserve_in = reserve_a
            reserve_out = reserve_b
        else:
            reserve_in = reserve_b
            reserve_out = reserve_a
        expected_out = reserve_out * amount_in_less_fee // (reserve_in + amount_in_less_fee)
        return expected_out * (10_000 - decision.max_slippage_bps) // 10_000

    def _planned_swap_changes(self, decision: TraderDecision) -> dict[str, int]:
        pool = self.scenario_pool(decision.pool_id or "")
        token_out = pool.quote_symbol if decision.token_in == pool.base_symbol else pool.base_symbol
        return {
            decision.token_in or "": -(decision.amount_in or 0),
            token_out: 0,
        }

    def _confirmed_swap_changes(self, decision: TraderDecision, event_data: dict[str, Any]) -> dict[str, int]:
        pool = self.scenario_pool(decision.pool_id or "")
        token_in = _event_value(event_data, "tokenIn", "token_in")
        if token_in is None:
            token_in = self._symbol_to_address(decision.token_in or "")
        token_in_symbol = self._address_to_symbol(str(token_in))
        token_out_symbol = pool.quote_symbol if token_in_symbol == pool.base_symbol else pool.base_symbol
        amount_in = _event_value(event_data, "amountIn", "amount_in")
        amount_out = _event_value(event_data, "amountOut", "amount_out")
        return {
            token_in_symbol: -int(amount_in if amount_in is not None else decision.amount_in or 0),
            token_out_symbol: int(amount_out if amount_out is not None else 0),
        }

    def scenario_pool(self, pool_id: str):
        for pool in self.scenario.pools:
            if pool.id == pool_id:
                return pool
        raise KeyError(f"unknown pool_id: {pool_id}")

    def _symbol_to_address(self, symbol: str) -> str:
        for token in self.scenario.tokens:
            if token.symbol == symbol:
                return token.address
        raise KeyError(f"unknown token symbol: {symbol}")

    def _address_to_symbol(self, address: str) -> str:
        normalized = address.lower()
        for token in self.scenario.tokens:
            if token.address.lower() == normalized:
                return token.symbol
        raise KeyError(f"unknown token address: {address}")


def build_agent(index: int, *, llm_override: str | None = None) -> TraderAgent:
    loaded = config.load()
    trader_config = loaded.traders[index]
    registry = ContractRegistry.from_rpc(loaded.scenario, loaded.rpc_url)
    reader = ChainReader(registry)
    account = registry.web3.eth.account.from_key(trader_config.private_key)
    model = llm_override or trader_config.model
    persona = load_persona(trader_config.persona_index)
    llm_client = create_llm_client(
        model,
        openai_api_key=loaded.openai_api_key,
        google_api_key=loaded.google_api_key,
        groq_api_key=loaded.groq_api_key,
        openrouter_api_key=loaded.openrouter_api_key,
        deepseek_api_key=loaded.deepseek_api_key,
        persona_prompt=persona,
    )
    return TraderAgent(
        trader_address=account.address,
        private_key=trader_config.private_key,
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
    feed = NewsFeed(NewsFeed.load_news(agent.scenario.news_file), agent.scenario)
    schedule = feed.schedule()

    if args.once:
        news = schedule[0].news if schedule else None
        result = agent.run_once(news)
        _print_result(result)
        return 0

    tick = 0
    while True:
        broadcasts = feed.broadcast_at(tick, [agent.trader_address])
        if broadcasts:
            _print_result(agent.run_once(broadcasts[agent.trader_address]))
        tick += 1
        time.sleep(args.interval)


def _serialize_news(news: NewsItem | dict[str, Any] | None) -> dict[str, Any] | None:
    if news is None:
        return None
    if isinstance(news, dict):
        return news
    return news.model_dump()


def _event_value(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def _print_result(result: TraderRunResult) -> None:
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
