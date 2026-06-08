import argparse
import json
import time
from pathlib import Path
from typing import Any

from agents import config
from agents.chain import ChainReader, ChainTransactionSubmitter, ContractRegistry, LocalValidator, ReceiptVerifier
from agents.coordinator import AgentCycleResult, CycleCoordinator, CycleResult
from agents.llm import create_llm_client, load_persona
from agents.lp_agent import LPAgent
from agents.news_feed import NewsFeed, Scenario
from agents.portfolio import Portfolio
from agents.trader_agent import TraderAgent


def build_coordinator(
    *,
    scenario_path: str,
    llm_override: str | None = None,
    min_cycle_seconds: float = 60.0,
    shuffle_execution: bool = True,
    shuffle_seed: int | None = None,
    news_count: int | None = None,
    news_every_cycle: bool = False,
    repeat_news: bool = False,
) -> CycleCoordinator:
    loaded = config.load(scenario_path=scenario_path)
    scenario = loaded.scenario
    if news_count is not None:
        if news_count <= 0:
            raise ValueError("--news-count must be positive")
        scenario = scenario.model_copy(update={"max_events": news_count})
    if news_every_cycle:
        scenario = scenario.model_copy(update={"min_interval_ticks": 1, "max_interval_ticks": 1})

    registry = ContractRegistry.from_rpc(scenario, loaded.rpc_url)
    reader = ChainReader(registry)
    validator = LocalValidator(reader)
    submitter = ChainTransactionSubmitter(registry)
    verifier = ReceiptVerifier(registry)

    traders = []
    for trader_config in loaded.traders:
        account = registry.web3.eth.account.from_key(trader_config.private_key)
        traders.append(
            TraderAgent(
                trader_address=account.address,
                private_key=trader_config.private_key,
                scenario=scenario,
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

    lp_agents = []
    for lp_config in loaded.lps:
        account = registry.web3.eth.account.from_key(lp_config.private_key)
        lp_agents.append(
            LPAgent(
                lp_address=account.address,
                private_key=lp_config.private_key,
                scenario=scenario,
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
        )

    news_feed = NewsFeed(NewsFeed.load_news(_resolve_news_path(scenario, scenario_path)), scenario, repeat_news=repeat_news)
    return CycleCoordinator(
        traders=traders,
        lp_agents=lp_agents,
        reader=reader,
        news_feed=news_feed,
        min_cycle_seconds=min_cycle_seconds,
        shuffle_execution=shuffle_execution,
        shuffle_seed=shuffle_seed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="data/scenarios/demo.json")
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--llm", default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-shuffle-execution", action="store_true")
    parser.add_argument("--shuffle-seed", type=int, default=None)
    parser.add_argument("--news-count", type=int, default=None)
    parser.add_argument("--news-every-cycle", action="store_true")
    parser.add_argument("--repeat-news", action="store_true")
    parser.add_argument("--max-cycles", type=int, default=None)
    args = parser.parse_args(argv)

    coordinator = build_coordinator(
        scenario_path=args.scenario,
        llm_override=args.llm,
        min_cycle_seconds=args.interval,
        shuffle_execution=not args.no_shuffle_execution,
        shuffle_seed=args.shuffle_seed,
        news_count=args.news_count,
        news_every_cycle=args.news_every_cycle,
        repeat_news=args.repeat_news,
    )

    if args.once:
        print(json.dumps(_cycle_result_payload(coordinator.run_cycle(0)), sort_keys=True))
        return 0

    stop_after_tick = _last_news_tick(coordinator) if args.news_count is not None else None
    tick = 0
    while True:
        cycle_start = time.time()
        print(json.dumps(_cycle_result_payload(coordinator.run_cycle(tick)), sort_keys=True))
        if stop_after_tick is not None and tick >= stop_after_tick:
            return 0
        if args.max_cycles is not None and tick + 1 >= args.max_cycles:
            return 0
        elapsed = time.time() - cycle_start
        time.sleep(max(0, args.interval - elapsed))
        tick += 1


def _resolve_news_path(scenario: Scenario, scenario_path: str) -> str:
    news_path = Path(scenario.news_file)
    if news_path.is_absolute() or news_path.exists():
        return str(news_path)
    return str((Path(scenario_path).resolve().parent / news_path).resolve())


def _cycle_result_payload(result: CycleResult) -> dict[str, Any]:
    return {
        "tick": result.tick,
        "agents": [_agent_result_payload(agent_result) for agent_result in result.agents],
    }


def _last_news_tick(coordinator: CycleCoordinator) -> int:
    if coordinator.news_feed is None:
        return 0
    schedule = coordinator.news_feed.schedule()
    if not schedule:
        return 0
    return max(item.tick for item in schedule)


def _agent_result_payload(agent_result: AgentCycleResult) -> dict[str, Any]:
    execution = agent_result.result.execution if agent_result.result else None
    validation = agent_result.result.validation if agent_result.result else None
    return {
        "agent_type": agent_result.agent_type,
        "address": agent_result.address,
        "decision": agent_result.decision.model_dump(),
        "validation": validation.ok if validation else False,
        "validation_reason": validation.reason if validation else agent_result.error,
        "tx_hash": agent_result.result.tx_hash if agent_result.result else None,
        "execution_status": execution.status if execution else None,
        "error": agent_result.error,
    }


if __name__ == "__main__":
    raise SystemExit(main())
