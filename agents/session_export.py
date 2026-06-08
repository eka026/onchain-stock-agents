"""Converts a DemoRunResult + live agents into an API Session ready to save."""

import uuid
from datetime import UTC, datetime
import json
import os
from pathlib import Path
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
    Reads current contract state and recent on-chain events.

    The dashboard import is intentionally a fast snapshot by default. Full-chain
    log scans and historical spotPrice calls are slow on public RPC providers, so
    callers can widen the log range with LIVE_IMPORT_FROM_BLOCK or
    LIVE_IMPORT_MAX_BLOCKS when they need older history.
    """
    from agents.chain import ChainReader, ContractRegistry
    from agents.news_feed import NewsFeed

    scenario = NewsFeed.load_scenario(scenario_path)
    registry = ContractRegistry.from_rpc(scenario, rpc_url)
    reader = ChainReader(registry)
    _reset_reader_cache(reader)
    _enable_reader_cache(reader)

    now = datetime.now(UTC)
    from_block, to_block = _live_import_block_range(registry)
    include_price_history = _truthy_env("LIVE_IMPORT_PRICE_HISTORY")
    pools: list[PoolSnapshot] = []
    for pool in scenario.pools:
        reserve_a, reserve_b = reader.reserves(pool.id)
        spot = reader.spot_price(pool.id)
        fee_bps = reader.pool_fee_bps(pool.id)
        history = reader.spot_price_history(pool.id) if include_price_history else [spot]
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

    event_source = os.environ.get("LIVE_IMPORT_EVENT_SOURCE", "local").strip().lower()
    if event_source == "chain":
        events = _chain_events_from_logs(registry, scenario, from_block=from_block, to_block=to_block)
    else:
        events = _chain_events_from_local_log(scenario)
    agent_snaps = _agent_snapshots_from_env(reader, scenario, events)
    confirmed = sum(1 for event in events if event.status == "confirmed")
    rejected = sum(1 for event in events if event.status == "rejected")
    _reset_reader_cache(reader)

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


def _agent_snapshots_from_env(reader, scenario, events: list[TimelineEvent] | None = None) -> list[AgentSnapshot]:
    agents: list[AgentSnapshot] = []
    seen: set[str] = set()
    for i, private_key in enumerate(_csv_env("TRADER_PRIVATE_KEYS")):
        address = Account.from_key(private_key).address
        balances = {token.symbol: str(reader.token_balance(token.symbol, address)) for token in scenario.tokens}
        seen.add(f"trader:{address}".lower())
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
        seen.add(f"lp:{address}".lower())
        agents.append(AgentSnapshot(
            id=f"lp:{address}",
            type="lp",
            label=f"LP {i}",
            address=address,
            balances=balances,
        ))

    for event in events or []:
        if not event.agent_id or not event.agent_type:
            continue
        if event.agent_id.lower() in seen:
            continue
        _prefix, _separator, address = event.agent_id.partition(":")
        if not address:
            continue
        balances = {token.symbol: str(reader.token_balance(token.symbol, address)) for token in scenario.tokens}
        if event.agent_type == "lp":
            for pool in scenario.pools:
                balances[f"{pool.id}-LP"] = str(reader.lp_balance(pool.id, address))
        label_index = sum(1 for agent in agents if agent.type == event.agent_type)
        seen.add(event.agent_id.lower())
        agents.append(AgentSnapshot(
            id=event.agent_id,
            type=event.agent_type,
            label=f"{event.agent_type.upper()} {label_index}",
            address=address,
            balances=balances,
        ))
    return agents


def _chain_events_from_logs(registry, scenario, *, from_block: int = 0, to_block: int | str | None = None) -> list[TimelineEvent]:
    events: list[tuple[int, int, TimelineEvent]] = []
    counter = 0

    def eid(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"chain-{prefix}-{counter}"

    for pool in scenario.pools:
        contracts = registry.pool_contracts(pool.id)
        for log in _safe_get_logs(contracts.pool.events.LiquidityAdded, from_block=from_block, to_block=to_block):
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

        for log in _safe_get_logs(contracts.pool.events.Swap, from_block=from_block, to_block=to_block):
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

        for log in _safe_get_logs(contracts.pool.events.LiquidityRemoved, from_block=from_block, to_block=to_block):
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

        for log in _safe_get_logs(contracts.vault.events.FeesCollected, from_block=from_block, to_block=to_block):
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


def _chain_events_from_local_log(scenario) -> list[TimelineEvent]:
    log_path = Path(os.environ.get("LIVE_IMPORT_LOG_PATH", "logs/events.json"))
    if not log_path.exists():
        return []

    max_entries = int(os.environ.get("LIVE_IMPORT_LOCAL_EVENT_LIMIT", "500"))
    entries = _read_recent_event_log_entries(log_path, max_entries=max_entries)
    action_by_tx = {
        str(event.get("tx_hash")): event
        for _timestamp, event in entries
        if event.get("type") == "action" and event.get("tx_hash")
    }

    events: list[TimelineEvent] = []
    seen_transactions: set[str] = set()
    counter = 0

    def eid(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"local-{prefix}-{counter}"

    for timestamp, event in entries:
        event_type = event.get("type")
        if event_type == "decision":
            address = str(event.get("address") or "")
            agent_type = _local_agent_type(event)
            events.append(TimelineEvent(
                id=eid("decision"),
                timestamp=timestamp,
                kind="agent_decision",
                agent_id=f"{agent_type}:{address}" if address and agent_type else None,
                agent_type=agent_type,
                pool_id=event.get("pool_id"),
                action=event.get("action"),
                status="ok",
                summary=str(event.get("reason") or event.get("action") or "Agent decision."),
            ))
            continue

        if event_type != "execution_result":
            continue

        tx_hash = event.get("tx_hash")
        if not tx_hash or tx_hash in seen_transactions:
            continue
        seen_transactions.add(str(tx_hash))

        action_event = action_by_tx.get(str(tx_hash), {})
        agent_type = _local_agent_type(event, action_event)
        address = _local_agent_address(event, action_event)
        status = "confirmed" if str(event.get("status", "")).upper() == "CONFIRMED" else "rejected"
        pool_id = event.get("pool_id") or action_event.get("pool_id")
        action = event.get("action") or action_event.get("action")
        reason = event.get("reason")

        events.append(TimelineEvent(
            id=eid("tx"),
            timestamp=timestamp,
            kind="transaction",
            agent_id=f"{agent_type}:{address}" if address and agent_type else None,
            agent_type=agent_type,
            pool_id=pool_id,
            action=action,
            status=status,
            summary=_local_transaction_summary(action, status, pool_id, reason),
            tx_hash=str(tx_hash),
            portfolio_delta=_local_portfolio_delta(scenario, pool_id, event, action_event),
        ))

    return events


def _read_recent_event_log_entries(log_path: Path, *, max_entries: int) -> list[tuple[datetime | None, dict[str, Any]]]:
    entries: list[tuple[datetime | None, dict[str, Any]]] = []
    with log_path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()

    for line in lines[-max_entries:]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = payload.get("event")
        if not isinstance(event, dict):
            continue
        entries.append((_parse_event_timestamp(payload.get("timestamp")), event))
    return entries


def _parse_event_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_agent_type(*events: dict[str, Any]) -> str | None:
    for event in events:
        if event.get("agent") in {"trader", "lp"}:
            return str(event["agent"])
        if event.get("trader"):
            return "trader"
        if event.get("lp"):
            return "lp"
    return None


def _local_agent_address(*events: dict[str, Any]) -> str:
    for event in events:
        for key in ("trader", "lp", "address"):
            value = event.get(key)
            if value:
                return str(value)
    return ""


def _local_transaction_summary(action: Any, status: str, pool_id: Any, reason: Any) -> str:
    if reason and status == "rejected":
        return str(reason)
    label = str(action or "Transaction").replace("_", " ").title()
    if pool_id:
        return f"{label} {status} on {pool_id}."
    return f"{label} {status}."


def _local_portfolio_delta(scenario, pool_id: Any, event: dict[str, Any], action_event: dict[str, Any]) -> dict[str, str] | None:
    if not pool_id or str(event.get("status", "")).upper() != "CONFIRMED":
        return None
    event_data = event.get("event_data")
    if not isinstance(event_data, dict):
        return None

    pool = next((item for item in scenario.pools if item.id == pool_id), None)
    if pool is None:
        return None

    amount_in = event_data.get("amountIn")
    amount_out = event_data.get("amountOut")
    if amount_in is None or amount_out is None:
        return None

    token_in_symbol = _symbol_for_address(scenario, str(event_data.get("tokenIn") or action_event.get("token_in") or ""))
    token_out_symbol = pool.quote_symbol if token_in_symbol == pool.base_symbol else pool.base_symbol
    return {
        token_in_symbol: f"-{int(amount_in)}",
        token_out_symbol: str(amount_out),
    }


def _safe_get_logs(event: Any, *, from_block: int = 0, to_block: int | str | None = None) -> list[Any]:
    try:
        if to_block is None:
            return list(event.get_logs(fromBlock=from_block))
        return list(event.get_logs(fromBlock=from_block, toBlock=to_block))
    except TypeError:
        try:
            return list(event.get_logs(fromBlock=from_block))
        except Exception:
            return []
    except Exception:
        return []


def _enable_reader_cache(reader: Any) -> None:
    enable_cache = getattr(reader, "enable_cache", None)
    if callable(enable_cache):
        enable_cache()


def _reset_reader_cache(reader: Any) -> None:
    reset_cache = getattr(reader, "reset_cache", None)
    if callable(reset_cache):
        reset_cache()


def _live_import_block_range(registry: Any) -> tuple[int, int | str | None]:
    explicit_from = os.environ.get("LIVE_IMPORT_FROM_BLOCK")
    if explicit_from:
        return max(0, int(explicit_from)), _to_block_env()

    latest_block = _latest_block(registry)
    max_blocks = int(os.environ.get("LIVE_IMPORT_MAX_BLOCKS", "10000"))
    if latest_block is None:
        return 0, _to_block_env()
    return max(0, latest_block - max_blocks), _to_block_env() or latest_block


def _latest_block(registry: Any) -> int | None:
    try:
        return int(registry.web3.eth.block_number)
    except Exception:
        return None


def _to_block_env() -> int | str | None:
    value = os.environ.get("LIVE_IMPORT_TO_BLOCK")
    if not value:
        return None
    if value.lower() == "latest":
        return "latest"
    return int(value)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
