"""Converts a DemoRunResult + live agents into an API Session ready to save."""

import uuid
from datetime import UTC, datetime
import os
from typing import Any

from eth_account import Account

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

    events = _chain_events_from_logs(registry, scenario)
    agent_snaps = _agent_snapshots_from_env(reader, scenario)
    confirmed = sum(1 for event in events if event.status == "confirmed")
    rejected = sum(1 for event in events if event.status == "rejected")

    return Session(
        id=f"live-{now.strftime('%Y%m%d-%H%M%S')}",
        name=f"Live Snapshot — {now.strftime('%Y-%m-%d %H:%M:%S')}",
        source="imported",
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


def _agent_snapshots_from_env(reader, scenario) -> list[AgentSnapshot]:
    agents: list[AgentSnapshot] = []
    for i, private_key in enumerate(_csv_env("TRADER_PRIVATE_KEYS")):
        address = Account.from_key(private_key).address
        balances = {token.symbol: str(reader.token_balance(token.symbol, address)) for token in scenario.tokens}
        agents.append(AgentSnapshot(
            id=f"trader:{address}",
            type="trader",
            label=f"Trader {i}",
            address=address,
            balances=balances,
        ))

    for i, private_key in enumerate(_csv_env("LP_PRIVATE_KEYS")):
        address = Account.from_key(private_key).address
        balances = {token.symbol: str(reader.token_balance(token.symbol, address)) for token in scenario.tokens}
        for pool in scenario.pools:
            balances[f"{pool.id}-LP"] = str(reader.lp_balance(pool.id, address))
        agents.append(AgentSnapshot(
            id=f"lp:{address}",
            type="lp",
            label=f"LP {i}",
            address=address,
            balances=balances,
        ))
    return agents


def _chain_events_from_logs(registry, scenario) -> list[TimelineEvent]:
    events: list[tuple[int, int, TimelineEvent]] = []
    counter = 0

    def eid(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"chain-{prefix}-{counter}"

    for pool in scenario.pools:
        contracts = registry.pool_contracts(pool.id)
        for log in _safe_get_logs(contracts.pool.events.LiquidityAdded):
            args = _log_args(log)
            provider = str(_event_value(args, "provider", default=""))
            events.append((
                _block_number(log),
                _log_index(log),
                TimelineEvent(
                    id=eid("liquidity-added"),
                    kind="transaction",
                    agent_id=f"lp:{provider}" if provider else None,
                    agent_type="lp",
                    pool_id=pool.id,
                    action="ADD_LIQUIDITY",
                    status="confirmed",
                    summary=f"Liquidity added to {pool.id}.",
                    tx_hash=_tx_hash(log),
                    portfolio_delta={
                        pool.base_symbol: f"-{int(_event_value(args, 'amountA', default=0))}",
                        pool.quote_symbol: f"-{int(_event_value(args, 'amountB', default=0))}",
                        f"{pool.id}-LP": str(_event_value(args, "lpShares", default=0)),
                    },
                ),
            ))

        for log in _safe_get_logs(contracts.pool.events.Swap):
            args = _log_args(log)
            trader = str(_event_value(args, "trader", default=""))
            token_in_address = str(_event_value(args, "tokenIn", "token_in", default=""))
            token_in_symbol = _symbol_for_address(scenario, token_in_address)
            token_out_symbol = pool.quote_symbol if token_in_symbol == pool.base_symbol else pool.base_symbol
            events.append((
                _block_number(log),
                _log_index(log),
                TimelineEvent(
                    id=eid("swap"),
                    kind="transaction",
                    agent_id=f"trader:{trader}" if trader else None,
                    agent_type="trader",
                    pool_id=pool.id,
                    action="SWAP",
                    status="confirmed",
                    summary=f"Swap confirmed on {pool.id}.",
                    tx_hash=_tx_hash(log),
                    portfolio_delta={
                        token_in_symbol: f"-{int(_event_value(args, 'amountIn', 'amount_in', default=0))}",
                        token_out_symbol: str(_event_value(args, "amountOut", "amount_out", default=0)),
                    },
                ),
            ))

        for log in _safe_get_logs(contracts.pool.events.LiquidityRemoved):
            args = _log_args(log)
            provider = str(_event_value(args, "provider", default=""))
            events.append((
                _block_number(log),
                _log_index(log),
                TimelineEvent(
                    id=eid("liquidity-removed"),
                    kind="transaction",
                    agent_id=f"lp:{provider}" if provider else None,
                    agent_type="lp",
                    pool_id=pool.id,
                    action="REMOVE_LIQUIDITY",
                    status="confirmed",
                    summary=f"Liquidity removed from {pool.id}.",
                    tx_hash=_tx_hash(log),
                ),
            ))

        for log in _safe_get_logs(contracts.vault.events.FeesCollected):
            args = _log_args(log)
            lp_address = str(_event_value(args, "lp", default=""))
            events.append((
                _block_number(log),
                _log_index(log),
                TimelineEvent(
                    id=eid("fees-collected"),
                    kind="transaction",
                    agent_id=f"lp:{lp_address}" if lp_address else None,
                    agent_type="lp",
                    pool_id=pool.id,
                    action="COLLECT_FEES",
                    status="confirmed",
                    summary=f"Fees collected from {pool.id}.",
                    tx_hash=_tx_hash(log),
                    portfolio_delta={
                        pool.base_symbol: str(_event_value(args, "feesA", default=0)),
                        pool.quote_symbol: str(_event_value(args, "feesB", default=0)),
                    },
                ),
            ))

    return [event for _block, _index, event in sorted(events, key=lambda item: (item[0], item[1], item[2].id))]


def _safe_get_logs(event: Any) -> list[Any]:
    try:
        return list(event.get_logs(fromBlock=0))
    except Exception:
        return []


def _log_args(log: Any) -> dict[str, Any]:
    if isinstance(log, dict):
        return dict(log.get("args", {}))
    return dict(getattr(log, "args", {}) or {})


def _event_value(args: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in args:
            return args[name]
    return default


def _block_number(log: Any) -> int:
    return int(_log_field(log, "blockNumber", 0) or 0)


def _log_index(log: Any) -> int:
    return int(_log_field(log, "logIndex", 0) or 0)


def _tx_hash(log: Any) -> str | None:
    value = _log_field(log, "transactionHash", None)
    if value is None:
        return None
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if hasattr(value, "hex"):
        text = value.hex()
        return text if text.startswith("0x") else "0x" + text
    return str(value)


def _log_field(log: Any, name: str, default: Any) -> Any:
    if isinstance(log, dict):
        return log.get(name, default)
    return getattr(log, name, default)


def _symbol_for_address(scenario, address: str) -> str:
    normalized = address.lower()
    for token in scenario.tokens:
        if token.address.lower() == normalized:
            return token.symbol
    return address


def _csv_env(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


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
