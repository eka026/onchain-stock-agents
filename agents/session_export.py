"""Converts a DemoRunResult + live agents into an API Session ready to save."""

import uuid
from datetime import UTC, datetime

from agents.lp_agent import LPAgent, LPRunResult
from agents.run_demo import DemoRunResult
from agents.trader_agent import TraderAgent, TraderRunResult
from api.models import AgentSnapshot, PoolSnapshot, Session, SessionSummary, TimelineEvent


def build_session_from_demo(
    result: DemoRunResult,
    lp_agent: LPAgent,
    trader_agents: list[TraderAgent],
    *,
    scenario_path: str = "",
    network: str = "local",
) -> Session:
    now = datetime.now(UTC)
    events: list[TimelineEvent] = []
    counter = 0

    def eid(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}-{counter}"

    for sched in result.schedule:
        events.append(TimelineEvent(
            id=eid("news"),
            tick=sched.tick,
            kind="news",
            summary=sched.news.headline,
            status="ok",
        ))

    if result.initial_liquidity is not None:
        events.extend(_lp_events(eid, tick=0, address=lp_agent.lp_address, r=result.initial_liquidity))

    for tick, addr, tr in result.trader_results:
        events.extend(_trader_events(eid, tick=tick, address=addr, r=tr))

    for neg in result.negative_results:
        r = neg.result
        if isinstance(r, TraderRunResult):
            events.extend(_trader_events(eid, tick=None, address="negative", r=r))
        elif isinstance(r, LPRunResult):
            events.extend(_lp_events(eid, tick=None, address=lp_agent.lp_address, r=r))

    if result.fee_collection is not None:
        events.extend(_lp_events(eid, tick=None, address=lp_agent.lp_address, r=result.fee_collection))

    if result.liquidity_removal is not None:
        events.extend(_lp_events(eid, tick=None, address=lp_agent.lp_address, r=result.liquidity_removal))

    # Pool snapshots — read final state from chain, include accumulated price history
    scenario = lp_agent.scenario
    reader = lp_agent.reader
    pools: list[PoolSnapshot] = []
    for pool in scenario.pools:
        reserve_a, reserve_b = reader.reserves(pool.id)
        spot = reader.spot_price(pool.id)
        fee_bps = reader.pool_fee_bps(pool.id)
        history = lp_agent.price_history.get(pool.base_symbol, [])
        pools.append(PoolSnapshot(
            id=pool.id,
            base_symbol=pool.base_symbol,
            quote_symbol=pool.quote_symbol,
            spot_price=str(spot),
            reserve_a=str(reserve_a),
            reserve_b=str(reserve_b),
            fee_bps=fee_bps,
            price_history=[str(p) for p in history] if history else None,
        ))

    # Agent snapshots — read final balances from chain
    agent_snaps: list[AgentSnapshot] = []
    for i, ta in enumerate(trader_agents):
        balances = {
            tok.symbol: str(reader.token_balance(tok.symbol, ta.trader_address))
            for tok in scenario.tokens
        }
        agent_snaps.append(AgentSnapshot(
            id=f"trader:{ta.trader_address}",
            type="trader",
            label=f"Trader {i}",
            address=ta.trader_address,
            balances=balances,
        ))

    lp_balances: dict[str, str] = {
        tok.symbol: str(reader.token_balance(tok.symbol, lp_agent.lp_address))
        for tok in scenario.tokens
    }
    for p in scenario.pools:
        lp_sym = f"{p.id}-LP"
        lp_balances[lp_sym] = str(reader.lp_balance(p.id, lp_agent.lp_address))
    agent_snaps.append(AgentSnapshot(
        id=f"lp:{lp_agent.lp_address}",
        type="lp",
        label="LP 0",
        address=lp_agent.lp_address,
        balances=lp_balances,
    ))

    confirmed = sum(1 for e in events if e.status == "confirmed")
    rejected = sum(1 for e in events if e.status == "rejected")

    return Session(
        id=str(uuid.uuid4()),
        name=f"Live Demo — {now.strftime('%Y-%m-%d %H:%M')}",
        source="live-demo",
        scenario_path=scenario_path,
        network=network,
        created_at=now,
        updated_at=now,
        summary=SessionSummary(
            agent_count=len(agent_snaps),
            event_count=len(events),
            confirmed_tx_count=confirmed,
            rejected_count=rejected,
        ),
        agents=agent_snaps,
        pools=pools,
        events=events,
    )


def build_session_from_chain(
    *,
    scenario_path: str,
    rpc_url: str,
    network: str = "local",
) -> Session:
    """
    Reads current contract state and reconstructs price history from on-chain events.
    For each pool, fetches spotPrice() at the block of every Swap event (plus the
    initial LiquidityAdded block) so the chart reflects the full history.
    """
    from agents.chain import ChainReader, ContractRegistry
    from agents.news_feed import NewsFeed

    scenario = NewsFeed.load_scenario(scenario_path)
    registry = ContractRegistry.from_rpc(scenario, rpc_url)
    reader = ChainReader(registry)

    now = datetime.now(UTC)
    pools: list[PoolSnapshot] = []
    for pool in scenario.pools:
        reserve_a, reserve_b = reader.reserves(pool.id)
        spot = reader.spot_price(pool.id)
        fee_bps = reader.pool_fee_bps(pool.id)
        history = reader.spot_price_history(pool.id)
        pools.append(PoolSnapshot(
            id=pool.id,
            base_symbol=pool.base_symbol,
            quote_symbol=pool.quote_symbol,
            spot_price=str(spot),
            reserve_a=str(reserve_a),
            reserve_b=str(reserve_b),
            fee_bps=fee_bps,
            price_history=[str(p) for p in history],
        ))

    return Session(
        id=f"live-{now.strftime('%Y%m%d-%H%M%S')}",
        name=f"Live Snapshot — {now.strftime('%Y-%m-%d %H:%M:%S')}",
        source="imported",
        scenario_path=scenario_path,
        network=network,
        created_at=now,
        updated_at=now,
        summary=SessionSummary(
            agent_count=0,
            event_count=0,
            confirmed_tx_count=0,
            rejected_count=0,
        ),
        agents=[],
        pools=pools,
        events=[],
    )


def _trader_events(eid, *, tick, address: str, r: TraderRunResult) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    agent_id = f"trader:{address}"

    summary = r.decision.reason[:100] if r.decision.reason else r.decision.action
    events.append(TimelineEvent(
        id=eid("decision"),
        tick=tick,
        kind="agent_decision",
        agent_id=agent_id,
        agent_type="trader",
        pool_id=r.decision.pool_id,
        action=r.decision.action,
        status="ok" if r.validation.ok else "rejected",
        summary=summary,
    ))

    if not r.validation.ok:
        events.append(TimelineEvent(
            id=eid("validation"),
            tick=tick,
            kind="validation",
            agent_id=agent_id,
            agent_type="trader",
            pool_id=r.decision.pool_id,
            action=r.decision.action,
            status="rejected",
            summary=r.validation.reason or "Validation failed.",
            validation_reason=r.validation.reason,
        ))
        return events

    if r.decision.action == "HOLD" or not r.tx_hash or not r.execution:
        return events

    tx_status = "confirmed" if r.execution.status == "CONFIRMED" else "rejected"
    events.append(TimelineEvent(
        id=eid("tx"),
        tick=tick,
        kind="transaction",
        agent_id=agent_id,
        agent_type="trader",
        pool_id=r.decision.pool_id,
        action=r.decision.action,
        status=tx_status,
        summary=f"SWAP {r.execution.status.lower()} on-chain.",
        tx_hash=r.tx_hash,
    ))
    return events


def _lp_events(eid, *, tick, address: str, r: LPRunResult) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    agent_id = f"lp:{address}"

    summary = r.decision.reason[:100] if r.decision.reason else r.decision.action
    events.append(TimelineEvent(
        id=eid("decision"),
        tick=tick,
        kind="agent_decision",
        agent_id=agent_id,
        agent_type="lp",
        pool_id=r.decision.pool_id,
        action=r.decision.action,
        status="ok" if r.validation.ok else "rejected",
        summary=summary,
    ))

    if not r.validation.ok:
        events.append(TimelineEvent(
            id=eid("validation"),
            tick=tick,
            kind="validation",
            agent_id=agent_id,
            agent_type="lp",
            pool_id=r.decision.pool_id,
            action=r.decision.action,
            status="rejected",
            summary=r.validation.reason or "Validation failed.",
            validation_reason=r.validation.reason,
        ))
        return events

    if r.decision.action == "HOLD" or not r.tx_hash or not r.execution:
        return events

    tx_status = "confirmed" if r.execution.status == "CONFIRMED" else "rejected"
    label = r.decision.action.replace("_", " ").title()
    events.append(TimelineEvent(
        id=eid("tx"),
        tick=tick,
        kind="transaction",
        agent_id=agent_id,
        agent_type="lp",
        pool_id=r.decision.pool_id,
        action=r.decision.action,
        status=tx_status,
        summary=f"{label} {r.execution.status.lower()} on-chain.",
        tx_hash=r.tx_hash,
    ))
    return events
