import { Activity, AlertTriangle, CheckCircle2, Download, RefreshCw, Timer, WalletCards } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getSession, importDemoSession, listSessions } from "./api";
import { filterEvents, formatAmount, shortenAddress } from "./format";
import type { AgentSnapshot, EventFilters, EventKind, EventStatus, PoolSnapshot, Session, SessionListItem, TimelineEvent } from "./types";

const ALL = "all";
const EVENT_KIND_OPTIONS: Array<EventKind | typeof ALL> = [ALL, "news", "agent_decision", "validation", "transaction", "portfolio_update"];
const STATUS_OPTIONS: Array<EventStatus | typeof ALL> = [ALL, "ok", "confirmed", "pending", "rejected"];

export default function App() {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [filters, setFilters] = useState<EventFilters>({ kind: ALL, status: ALL, poolId: ALL, agentId: ALL });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void refreshSessions();
  }, []);

  const visibleEvents = useMemo(() => filterEvents(session?.events ?? [], filters), [filters, session]);
  const selectedEvent = visibleEvents.find((event) => event.id === selectedEventId) ?? visibleEvents[0] ?? null;

  async function refreshSessions() {
    setLoading(true);
    setError(null);
    try {
      const loadedSessions = await listSessions();
      setSessions(loadedSessions);
      if (loadedSessions.length > 0) {
        const fullSession = await getSession(loadedSessions[0].id);
        setSession(fullSession);
        setSelectedEventId(fullSession.events[0]?.id ?? null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }

  async function loadSampleSession() {
    setLoading(true);
    setError(null);
    try {
      const imported = await importDemoSession();
      setSession(imported);
      setSessions([
        {
          id: imported.id,
          name: imported.name,
          source: imported.source,
          createdAt: imported.createdAt,
          updatedAt: imported.updatedAt,
          summary: imported.summary,
        },
      ]);
      setSelectedEventId(imported.events[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import sample session");
    } finally {
      setLoading(false);
    }
  }

  function updateFilter<Key extends keyof EventFilters>(key: Key, value: EventFilters[Key]) {
    setFilters((current) => ({ ...current, [key]: value }));
    setSelectedEventId(null);
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">On-chain stock agents</p>
          <h1>{session?.name ?? "Dashboard"}</h1>
          <p className="meta">
            {session ? `${session.source} / ${session.network ?? "local"} / ${session.scenarioPath ?? "scenario unavailable"}` : "No active session"}
          </p>
        </div>
        <div className="toolbar">
          {session ? (
            <button type="button" onClick={loadSampleSession} disabled={loading}>
              <Download size={16} aria-hidden="true" />
              Load sample session
            </button>
          ) : null}
          <button type="button" onClick={refreshSessions} disabled={loading}>
            <RefreshCw size={16} aria-hidden="true" />
            Refresh
          </button>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      {session ? (
        <>
          <Metrics session={session} />
          <section className="dashboard-grid">
            <div className="main-column">
              <PoolOverview pools={session.pools} />
              <Filters filters={filters} session={session} onChange={updateFilter} />
              <Timeline events={visibleEvents} selectedEventId={selectedEvent?.id} onSelect={setSelectedEventId} />
            </div>
            <aside className="side-column">
              <EventDetails event={selectedEvent} />
              <AgentPortfolios agents={session.agents} />
            </aside>
          </section>
        </>
      ) : (
        <section className="empty-state">
          <Activity size={32} aria-hidden="true" />
          <h2>No sessions loaded</h2>
          <p>Import a sample run to inspect agent actions, pool state, and final portfolios.</p>
          <button type="button" onClick={loadSampleSession} disabled={loading}>
            <Download size={16} aria-hidden="true" />
            Load sample session
          </button>
        </section>
      )}
    </main>
  );
}

function Metrics({ session }: { session: Session }) {
  const metrics = [
    { label: "Agents", value: session.summary.agentCount, icon: WalletCards },
    { label: "Events", value: session.summary.eventCount, icon: Timer },
    { label: "Confirmed tx", value: session.summary.confirmedTxCount, icon: CheckCircle2 },
    { label: "Rejected", value: session.summary.rejectedCount, icon: AlertTriangle },
  ];
  return (
    <section className="metrics" aria-label="Session metrics">
      {metrics.map((metric) => {
        const Icon = metric.icon;
        return (
          <div className="metric" key={metric.label}>
            <Icon size={18} aria-hidden="true" />
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
          </div>
        );
      })}
    </section>
  );
}

function PoolOverview({ pools }: { pools: PoolSnapshot[] }) {
  return (
    <section>
      <div className="section-heading">
        <h2>Markets</h2>
      </div>
      <div className="pool-grid">
        {pools.map((pool) => (
          <article className="pool-card" key={pool.id}>
            <div className="pool-title">
              <h3>{pool.id}</h3>
              {pool.feeBps !== undefined ? <span>{pool.feeBps} bps</span> : null}
            </div>
            <dl>
              <div>
                <dt>Spot</dt>
                <dd>{pool.spotPrice ? formatAmount(pool.spotPrice) : "n/a"}</dd>
              </div>
              <div>
                <dt>{pool.baseSymbol}</dt>
                <dd>{pool.reserveA ? formatAmount(pool.reserveA) : "n/a"}</dd>
              </div>
              <div>
                <dt>{pool.quoteSymbol}</dt>
                <dd>{pool.reserveB ? formatAmount(pool.reserveB) : "n/a"}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function Filters({
  filters,
  session,
  onChange,
}: {
  filters: EventFilters;
  session: Session;
  onChange: <Key extends keyof EventFilters>(key: Key, value: EventFilters[Key]) => void;
}) {
  return (
    <section className="filters" aria-label="Timeline filters">
      <label>
        Kind
        <select value={filters.kind} onChange={(event) => onChange("kind", event.target.value as EventFilters["kind"])}>
          {EVENT_KIND_OPTIONS.map((kind) => (
            <option value={kind} key={kind}>
              {labelize(kind)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Status
        <select value={filters.status} onChange={(event) => onChange("status", event.target.value as EventFilters["status"])}>
          {STATUS_OPTIONS.map((status) => (
            <option value={status} key={status}>
              {labelize(status)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Pool
        <select value={filters.poolId} onChange={(event) => onChange("poolId", event.target.value)}>
          <option value={ALL}>All</option>
          {session.pools.map((pool) => (
            <option value={pool.id} key={pool.id}>
              {pool.id}
            </option>
          ))}
        </select>
      </label>
      <label>
        Agent
        <select value={filters.agentId} onChange={(event) => onChange("agentId", event.target.value)}>
          <option value={ALL}>All</option>
          {session.agents.map((agent) => (
            <option value={agent.id} key={agent.id}>
              {agent.label}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

function Timeline({
  events,
  selectedEventId,
  onSelect,
}: {
  events: TimelineEvent[];
  selectedEventId?: string;
  onSelect: (eventId: string) => void;
}) {
  return (
    <section>
      <div className="section-heading">
        <h2>Timeline</h2>
        <span>{events.length} shown</span>
      </div>
      <div className="timeline">
        {events.length === 0 ? <p className="muted">No events match the current filters.</p> : null}
        {events.map((event) => (
          <button
            type="button"
            className={`timeline-row ${event.id === selectedEventId ? "selected" : ""}`}
            key={event.id}
            onClick={() => onSelect(event.id)}
          >
            <span className="tick">{event.tick !== undefined ? `T${event.tick}` : "--"}</span>
            <span className={`status ${event.status ?? "none"}`}>{event.status ?? "none"}</span>
            <span className="event-main">
              <strong>{event.summary}</strong>
              <small>
                {labelize(event.kind)}
                {event.action ? ` / ${event.action}` : ""}
                {event.agentType ? ` / ${event.agentType}` : ""}
                {event.poolId ? ` / Pool ${event.poolId}` : ""}
              </small>
            </span>
            {event.txHash ? <span className="hash">{shortenAddress(event.txHash)}</span> : null}
          </button>
        ))}
      </div>
    </section>
  );
}

function EventDetails({ event }: { event: TimelineEvent | null }) {
  if (!event) {
    return (
      <section className="panel">
        <h2>Event details</h2>
        <p className="muted">Select an event from the timeline.</p>
      </section>
    );
  }
  return (
    <section className="panel">
      <h2>Event details</h2>
      <dl className="detail-list">
        <div>
          <dt>Summary</dt>
          <dd>{event.summary}</dd>
        </div>
        <div>
          <dt>Kind</dt>
          <dd>{labelize(event.kind)}</dd>
        </div>
        {event.action ? (
          <div>
            <dt>Action</dt>
            <dd>{event.action}</dd>
          </div>
        ) : null}
        {event.status ? (
          <div>
            <dt>Status</dt>
            <dd>{event.status}</dd>
          </div>
        ) : null}
        {event.txHash ? (
          <div>
            <dt>Transaction</dt>
            <dd>{shortenAddress(event.txHash)}</dd>
          </div>
        ) : null}
        {event.validationReason ? (
          <div>
            <dt>Validation</dt>
            <dd>{event.validationReason}</dd>
          </div>
        ) : null}
      </dl>
      {event.portfolioDelta ? (
        <div className="delta-list">
          <h3>Portfolio delta</h3>
          {Object.entries(event.portfolioDelta).map(([symbol, value]) => (
            <span key={symbol}>
              {symbol} {formatAmount(value)}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function AgentPortfolios({ agents }: { agents: AgentSnapshot[] }) {
  return (
    <section className="panel">
      <h2>Portfolios</h2>
      <div className="agent-list">
        {agents.map((agent) => (
          <article className="agent-card" key={agent.id}>
            <div>
              <h3>{agent.label}</h3>
              <p>
                {agent.type} / {shortenAddress(agent.address)}
              </p>
            </div>
            <dl>
              {Object.entries(agent.balances).map(([symbol, value]) => (
                <div key={symbol}>
                  <dt>{symbol}</dt>
                  <dd>{formatAmount(value)}</dd>
                </div>
              ))}
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function labelize(value: string): string {
  if (value === ALL) {
    return "All";
  }
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
