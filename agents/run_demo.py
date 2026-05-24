import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents import config
from agents.chain import ChainReader, ChainTransactionSubmitter, ContractRegistry, LocalValidator, ReceiptVerifier
from agents.llm import create_llm_client, load_persona
from agents.lp_agent import LPAgent, LPRunResult
from agents.news_feed import NewsFeed, ScheduledNews, Scenario
from agents.portfolio import Portfolio
from agents.schemas import LPDecision, TraderDecision
from agents.trader_agent import TraderAgent, TraderRunResult


ONE = 10**18
DISABLED_TRADER_ADDRESS = "0x000000000000000000000000000000000000dead"
DISABLED_LP_ADDRESS = "0x000000000000000000000000000000000000d1ab"


@dataclass(frozen=True)
class NegativeScenarioResult:
    name: str
    result: TraderRunResult | LPRunResult


@dataclass
class DemoRunResult:
    schedule: list[ScheduledNews]
    initial_liquidity: LPRunResult | None = None
    trader_results: list[tuple[int, str, TraderRunResult]] = field(default_factory=list)
    fee_collection: LPRunResult | None = None
    liquidity_removal: LPRunResult | None = None
    negative_results: list[NegativeScenarioResult] = field(default_factory=list)
    final_portfolios: dict[str, dict[str, int]] = field(default_factory=dict)


def build_demo_agents(
    *,
    scenario_path: str,
    llm_override: str | None = None,
    trader_count: int = 2,
) -> tuple[LPAgent, list[TraderAgent], Scenario]:
    loaded = config.load(scenario_path=scenario_path)
    if not loaded.lps:
        raise RuntimeError("demo requires at least one LP_PRIVATE_KEYS entry")
    if len(loaded.traders) < trader_count:
        raise RuntimeError(f"demo requires at least {trader_count} trader private keys")
    _validate_deployed_addresses(loaded.scenario)

    registry = ContractRegistry.from_rpc(loaded.scenario, loaded.rpc_url)
    reader = ChainReader(registry)
    validator = LocalValidator(reader)
    submitter = ChainTransactionSubmitter(registry)
    verifier = ReceiptVerifier(registry)

    lp_config = loaded.lps[0]
    lp_account = registry.web3.eth.account.from_key(lp_config.private_key)
    lp_agent = LPAgent(
        lp_address=lp_account.address,
        private_key=lp_config.private_key,
        scenario=loaded.scenario,
        reader=reader,
        validator=validator,
        submitter=submitter,
        verifier=verifier,
        llm_client=create_llm_client(
            llm_override or lp_config.model,
            openai_api_key=loaded.openai_api_key,
            google_api_key=loaded.google_api_key,
            groq_api_key=loaded.groq_api_key,
            openrouter_api_key=loaded.openrouter_api_key,
            deepseek_api_key=loaded.deepseek_api_key,
            persona_prompt=load_persona(lp_config.persona_index),
        ),
        portfolio=Portfolio(),
    )

    trader_agents = []
    for trader_config in loaded.traders[:trader_count]:
        account = registry.web3.eth.account.from_key(trader_config.private_key)
        trader_agents.append(
            TraderAgent(
                trader_address=account.address,
                private_key=trader_config.private_key,
                scenario=loaded.scenario,
                reader=reader,
                validator=validator,
                submitter=submitter,
                verifier=verifier,
                llm_client=create_llm_client(
                    llm_override or trader_config.model,
                    openai_api_key=loaded.openai_api_key,
                    google_api_key=loaded.google_api_key,
                    groq_api_key=loaded.groq_api_key,
                    openrouter_api_key=loaded.openrouter_api_key,
                    deepseek_api_key=loaded.deepseek_api_key,
                    persona_prompt=load_persona(trader_config.persona_index),
                ),
                portfolio=Portfolio(),
            )
        )

    return lp_agent, trader_agents, loaded.scenario


def run_demo(
    *,
    scenario_path: str,
    llm_override: str | None = None,
    lp_agent: LPAgent | None = None,
    trader_agents: list[TraderAgent] | None = None,
    news_feed: NewsFeed | None = None,
) -> DemoRunResult:
    if lp_agent is None or trader_agents is None:
        lp_agent, trader_agents, scenario = build_demo_agents(
            scenario_path=scenario_path,
            llm_override=llm_override,
        )
    else:
        scenario = lp_agent.scenario

    if len(trader_agents) < 2:
        raise RuntimeError("demo requires at least two trader agents")

    feed = news_feed or NewsFeed(NewsFeed.load_news(_resolve_news_path(scenario, scenario_path)), scenario)
    result = DemoRunResult(schedule=feed.schedule())

    result.initial_liquidity = _run_lp_action(lp_agent, "ADD_LIQUIDITY")

    trader_ids = [agent.trader_address for agent in trader_agents]
    for scheduled in result.schedule:
        broadcasts = feed.broadcast_at(scheduled.tick, trader_ids)
        for agent in trader_agents:
            news = broadcasts.get(agent.trader_address)
            if news is None:
                continue
            result.trader_results.append((scheduled.tick, agent.trader_address, agent.run_once(news)))

    result.negative_results = _run_negative_scenarios(lp_agent, trader_agents[0])
    result.fee_collection = _run_lp_action(lp_agent, "COLLECT_FEES")
    result.liquidity_removal = _run_lp_action(lp_agent, "REMOVE_LIQUIDITY")
    result.final_portfolios = _final_portfolios(lp_agent, trader_agents)
    return result


def _run_lp_action(lp_agent: LPAgent, action: str) -> LPRunResult:
    observation = lp_agent.observe()
    decision = _deterministic_lp_decision(action, observation)
    return lp_agent.execute(decision)


def _deterministic_lp_decision(action: str, observation: dict[str, Any]) -> LPDecision:
    pools = observation.get("pools", [])
    if not pools:
        return LPDecision(action="HOLD", reason="Demo found no configured pools.")

    pool = pools[0]
    if action == "ADD_LIQUIDITY":
        amount_a = _default_liquidity_amount(
            balance=int(pool.get("base_balance", 0)),
            policy_limit=int(observation.get("policy", {}).get("max_liquidity_add", 0)),
        )
        amount_b = _default_liquidity_amount(
            balance=int(pool.get("quote_balance", 0)),
            policy_limit=int(observation.get("policy", {}).get("max_liquidity_add", 0)),
        )
        if amount_a <= 0 or amount_b <= 0:
            return LPDecision(action="HOLD", reason="Demo LP has no positive liquidity amount available.")
        return LPDecision(
            action="ADD_LIQUIDITY",
            pool_id=pool["id"],
            amount_a=amount_a,
            amount_b=amount_b,
            min_lp_shares=0,
            reason="Demo step: add initial liquidity.",
        )

    if action in {"REMOVE_LIQUIDITY", "COLLECT_FEES"}:
        lp_shares = _default_lp_shares(observation)
        return LPDecision(
            action=action,
            pool_id=pool["id"],
            lp_shares=lp_shares,
            reason=f"Demo step: {action.lower().replace('_', ' ')}.",
        )

    raise ValueError(f"unsupported LP demo action: {action}")


def _run_negative_scenarios(lp_agent: LPAgent, trader_agent: TraderAgent) -> list[NegativeScenarioResult]:
    pool = trader_agent.scenario.pools[0]
    trader_observation = trader_agent.observe()
    policy = trader_observation["policy"]
    oversized_amount = max(
        int(policy.get("max_swap_amount", 0)),
        int(policy.get("remaining_spending", 0)),
        0,
    ) + 1

    results = [
        NegativeScenarioResult(
            "oversized_swap",
            trader_agent.execute(
                TraderDecision(
                    action="SWAP",
                    pool_id=pool.id,
                    token_in=pool.quote_symbol,
                    amount_in=oversized_amount,
                    reason="Demo negative scenario: exceed trader policy limits.",
                )
            ),
        )
    ]

    unapproved_symbol = _first_unapproved_pool_symbol(trader_agent, pool)
    if unapproved_symbol is not None:
        results.append(
            NegativeScenarioResult(
                "unapproved_token_swap",
                trader_agent.execute(
                    TraderDecision(
                        action="SWAP",
                        pool_id=pool.id,
                        token_in=unapproved_symbol,
                        amount_in=1,
                        reason="Demo negative scenario: use an unapproved token.",
                    )
                ),
            )
        )

    disabled_trader = _clone_trader_for_address(trader_agent, DISABLED_TRADER_ADDRESS)
    results.append(
        NegativeScenarioResult(
            "disabled_trader_swap",
            disabled_trader.execute(
                TraderDecision(
                    action="SWAP",
                    pool_id=pool.id,
                    token_in=pool.quote_symbol,
                    amount_in=1,
                    reason="Demo negative scenario: use a trader without an enabled policy.",
                )
            ),
        )
    )

    lp_observation = lp_agent.observe()
    fee_limit_decision = _fee_limit_decision(lp_observation)
    if fee_limit_decision is not None:
        results.append(
            NegativeScenarioResult(
                "fee_withdrawal_limit",
                lp_agent.execute(fee_limit_decision),
            )
        )

    disabled_lp = _clone_lp_for_address(lp_agent, DISABLED_LP_ADDRESS)
    results.append(
        NegativeScenarioResult(
            "disabled_lp_action",
            disabled_lp.execute(
                LPDecision(
                    action="ADD_LIQUIDITY",
                    pool_id=pool.id,
                    amount_a=1,
                    amount_b=1,
                    reason="Demo negative scenario: use an LP without an enabled policy.",
                )
            ),
        )
    )
    return results


def _fee_limit_decision(observation: dict[str, Any]) -> LPDecision | None:
    pools = observation.get("pools", [])
    if not pools:
        return None

    pool = pools[0]
    total_fees = int(pool.get("fees_a", 0)) + int(pool.get("fees_b", 0))
    total_supply = int(pool.get("lp_total_supply", 0))
    if total_fees <= 0 or total_supply <= 0:
        return None

    policy = observation.get("policy", {})
    remaining = max(int(policy.get("max_fee_withdrawal", 0)) - int(policy.get("withdrawn_fees", 0)), 0)
    lp_shares = (remaining + 1) * total_supply // total_fees + 1
    return LPDecision(
        action="COLLECT_FEES",
        pool_id=pool["id"],
        lp_shares=lp_shares,
        reason="Demo negative scenario: exceed LP fee-withdrawal policy limit.",
    )


def _clone_trader_for_address(agent: TraderAgent, address: str) -> TraderAgent:
    return TraderAgent(
        trader_address=address,
        private_key=agent.private_key,
        scenario=agent.scenario,
        reader=agent.reader,
        validator=agent.validator,
        submitter=agent.submitter,
        verifier=agent.verifier,
        llm_client=agent.llm_client,
        portfolio=Portfolio(),
    )


def _clone_lp_for_address(agent: LPAgent, address: str) -> LPAgent:
    return LPAgent(
        lp_address=address,
        private_key=agent.private_key,
        scenario=agent.scenario,
        reader=agent.reader,
        validator=agent.validator,
        submitter=agent.submitter,
        verifier=agent.verifier,
        llm_client=agent.llm_client,
        portfolio=Portfolio(),
    )


def _first_unapproved_pool_symbol(trader_agent: TraderAgent, pool: Any) -> str | None:
    for symbol in (pool.base_symbol, pool.quote_symbol):
        try:
            if not trader_agent.reader.is_token_approved(symbol):
                return symbol
        except Exception:
            continue
    return None


def _default_liquidity_amount(*, balance: int, policy_limit: int) -> int:
    candidates = [value for value in (balance, policy_limit, ONE) if value > 0]
    return min(candidates) if candidates else 0


def _default_lp_shares(observation: dict[str, Any]) -> int:
    pools = observation.get("pools", [])
    if not pools:
        return ONE
    first_pool = pools[0]
    lp_balance = int(first_pool.get("lp_balance", 0))
    return max(1, lp_balance // 2) if lp_balance > 0 else ONE


def _final_portfolios(lp_agent: LPAgent, trader_agents: list[TraderAgent]) -> dict[str, dict[str, int]]:
    portfolios = {f"lp:{lp_agent.lp_address}": dict(lp_agent.portfolio.balances)}
    for agent in trader_agents:
        portfolios[f"trader:{agent.trader_address}"] = dict(agent.portfolio.balances)
    return portfolios


def _resolve_news_path(scenario: Scenario, scenario_path: str) -> str:
    news_path = Path(scenario.news_file)
    if news_path.is_absolute() or news_path.exists():
        return str(news_path)
    return str((Path(scenario_path).resolve().parent / news_path).resolve())


def _validate_deployed_addresses(scenario: Scenario) -> None:
    placeholder_fields = []
    if _looks_like_placeholder_address(scenario.policy_address):
        placeholder_fields.append("policy_address")

    for token in scenario.tokens:
        if _looks_like_placeholder_address(token.address):
            placeholder_fields.append(f"tokens.{token.symbol}.address")

    for pool in scenario.pools:
        for field_name in ("pool_address", "lp_token_address", "vault_address"):
            if _looks_like_placeholder_address(getattr(pool, field_name)):
                placeholder_fields.append(f"pools.{pool.id}.{field_name}")

    if placeholder_fields:
        preview = ", ".join(placeholder_fields[:5])
        suffix = "" if len(placeholder_fields) <= 5 else f", and {len(placeholder_fields) - 5} more"
        raise RuntimeError(f"scenario contains placeholder contract addresses: {preview}{suffix}")


def _looks_like_placeholder_address(address: str) -> bool:
    normalized = address.lower()
    return normalized == "0x0000000000000000000000000000000000000000" or normalized.startswith(
        "0x0000000000000000000000000000000000000"
    )


def print_demo_result(result: DemoRunResult) -> None:
    print({"step": "schedule", "events": [{"tick": item.tick, "news_id": item.news.id} for item in result.schedule]})
    if result.initial_liquidity is not None:
        _print_agent_result("initial_liquidity", result.initial_liquidity)
    for tick, trader, trader_result in result.trader_results:
        _print_agent_result("trader_broadcast", trader_result, {"tick": tick, "trader": trader})
    if result.fee_collection is not None:
        _print_agent_result("fee_collection", result.fee_collection)
    if result.liquidity_removal is not None:
        _print_agent_result("liquidity_removal", result.liquidity_removal)
    for negative in result.negative_results:
        _print_agent_result(f"negative:{negative.name}", negative.result)
    print({"step": "final_portfolios", "portfolios": result.final_portfolios})


def _print_agent_result(step: str, result: TraderRunResult | LPRunResult, extra: dict[str, Any] | None = None) -> None:
    execution_status = result.execution.status if result.execution else None
    payload = {
        "step": step,
        "decision": result.decision.model_dump(),
        "validation": result.validation.ok,
        "validation_reason": result.validation.reason,
        "tx_hash": result.tx_hash,
        "execution_status": execution_status,
    }
    if extra:
        payload.update(extra)
    print(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="data/scenarios/demo.json")
    parser.add_argument("--llm", default=None)
    args = parser.parse_args(argv)

    result = run_demo(scenario_path=args.scenario, llm_override=args.llm)
    print_demo_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
