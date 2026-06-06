import time
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from agents.chain import ChainReader
from agents.llm import LLMDecisionError
from agents.lp_agent import LPAgent, LPRunResult
from agents.news_feed import NewsFeed
from agents.schemas import LPDecision, TraderDecision
from agents.trader_agent import TraderAgent, TraderRunResult
from utils.logger import log


@dataclass(frozen=True)
class AgentCycleResult:
    agent_type: str
    address: str
    observation: dict[str, Any] | None
    decision: TraderDecision | LPDecision
    result: TraderRunResult | LPRunResult | None
    error: str | None = None


@dataclass(frozen=True)
class CycleResult:
    tick: int
    agents: list[AgentCycleResult]


class CycleCoordinator:
    def __init__(
        self,
        traders: list[TraderAgent],
        lp_agents: list[LPAgent],
        reader: ChainReader,
        news_feed: NewsFeed | None = None,
        min_cycle_seconds: float = 60.0,
        shuffle_execution: bool = True,
        shuffle_seed: int | None = None,
    ):
        self.traders = traders
        self.lp_agents = lp_agents
        self.reader = reader
        self.news_feed = news_feed
        self.min_cycle_seconds = min_cycle_seconds
        self.shuffle_execution = shuffle_execution
        self.shuffle_seed = shuffle_seed

    def run_cycle(self, tick: int = 0) -> CycleResult:
        self.reader.reset_cache()
        self.reader.enable_cache()
        try:
            observed = self._observe_agents(tick)
            decisions = self._decide_agents(observed)
            results = self._execute_agents(observed, decisions, tick=tick)
            return CycleResult(tick=tick, agents=results)
        finally:
            self.reader.reset_cache()

    def run_forever(self) -> None:
        tick = 0
        while True:
            cycle_start = time.time()
            self.run_cycle(tick)
            elapsed = time.time() - cycle_start
            time.sleep(max(0, self.min_cycle_seconds - elapsed))
            tick += 1

    def _observe_agents(self, tick: int) -> list[tuple[str, TraderAgent | LPAgent, dict[str, Any]]]:
        observed: list[tuple[str, TraderAgent | LPAgent, dict[str, Any]]] = []
        broadcasts = self._broadcasts(tick)

        for trader in self.traders:
            news = broadcasts.get(trader.trader_address)
            observation = trader.observe(news)
            log({"type": "observation", "agent": "trader", "trader_address": trader.trader_address, "tick": tick})
            observed.append(("trader", trader, observation))

        for lp_agent in self.lp_agents:
            observation = lp_agent.observe()
            log({"type": "observation", "agent": "lp", "lp_address": lp_agent.lp_address, "tick": tick})
            observed.append(("lp", lp_agent, observation))

        return observed

    def _broadcasts(self, tick: int) -> dict[str, Any]:
        if self.news_feed is None:
            return {}
        trader_ids = [trader.trader_address for trader in self.traders]
        return self.news_feed.broadcast_at(tick, trader_ids)

    def _decide_agents(
        self,
        observed: list[tuple[str, TraderAgent | LPAgent, dict[str, Any]]],
    ) -> dict[int, TraderDecision | LPDecision]:
        with ThreadPoolExecutor(max_workers=max(1, len(observed))) as executor:
            futures = {
                executor.submit(agent.decide, observation): index
                for index, (_agent_type, agent, observation) in enumerate(observed)
            }

            decisions: dict[int, TraderDecision | LPDecision] = {}
            for future, index in futures.items():
                agent_type, agent, _observation = observed[index]
                try:
                    decision = future.result()
                    self._log_decision(agent_type, agent, decision)
                except (LLMDecisionError, Exception) as exc:
                    decision = self._hold_decision(agent_type, str(exc))
                    self._log_decision_error(agent_type, agent, exc)
                decisions[index] = decision

        return decisions

    def _execute_agents(
        self,
        observed: list[tuple[str, TraderAgent | LPAgent, dict[str, Any]]],
        decisions: dict[int, TraderDecision | LPDecision],
        *,
        tick: int,
    ) -> list[AgentCycleResult]:
        results: list[AgentCycleResult] = []
        execution_order = list(range(len(observed)))
        if self.shuffle_execution and len(execution_order) > 1:
            seed = self.shuffle_seed if self.shuffle_seed is not None else int(time.time_ns())
            random.Random(f"{seed}:{tick}").shuffle(execution_order)
        log({"type": "cycle_execution_order", "tick": tick, "order": [self._observed_address(observed[index]) for index in execution_order]})

        for index in execution_order:
            agent_type, agent, observation = observed[index]
            decision = decisions[index]
            try:
                result = agent.execute(decision)  # type: ignore[arg-type]
                results.append(
                    AgentCycleResult(
                        agent_type=agent_type,
                        address=self._agent_address(agent_type, agent),
                        observation=observation,
                        decision=decision,
                        result=result,
                    )
                )
            except Exception as exc:
                log(
                    {
                        "type": "error",
                        "method": "cycle_execute",
                        "agent": agent_type,
                        "address": self._agent_address(agent_type, agent),
                        "error": str(exc),
                    }
                )
                results.append(
                    AgentCycleResult(
                        agent_type=agent_type,
                        address=self._agent_address(agent_type, agent),
                        observation=observation,
                        decision=decision,
                        result=None,
                        error=str(exc),
                    )
                )

        return results

    def _hold_decision(self, agent_type: str, reason: str) -> TraderDecision | LPDecision:
        if agent_type == "trader":
            return TraderDecision(action="HOLD", reason=reason)
        return LPDecision(action="HOLD", reason=reason)

    def _log_decision(self, agent_type: str, agent: TraderAgent | LPAgent, decision: TraderDecision | LPDecision) -> None:
        payload = {
            "type": "decision",
            "agent": agent_type,
            "address": self._agent_address(agent_type, agent),
            "action": decision.action,
            "pool_id": decision.pool_id,
            "reason": decision.reason,
        }
        if isinstance(decision, TraderDecision):
            payload["token_in"] = decision.token_in
            payload["amount_in"] = decision.amount_in
        log(payload)

    def _log_decision_error(self, agent_type: str, agent: TraderAgent | LPAgent, exc: Exception) -> None:
        log(
            {
                "type": "error",
                "method": "cycle_decide",
                "agent": agent_type,
                "address": self._agent_address(agent_type, agent),
                "error": str(exc),
            }
        )

    def _agent_address(self, agent_type: str, agent: TraderAgent | LPAgent) -> str:
        if agent_type == "trader":
            return agent.trader_address  # type: ignore[union-attr]
        return agent.lp_address  # type: ignore[union-attr]

    def _observed_address(self, observed: tuple[str, TraderAgent | LPAgent, dict[str, Any]]) -> str:
        agent_type, agent, _observation = observed
        return self._agent_address(agent_type, agent)
