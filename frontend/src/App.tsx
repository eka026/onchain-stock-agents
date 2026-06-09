import { Activity, AlertTriangle, CheckCircle2, Download, RefreshCw, Timer, TrendingUp, Wifi, WalletCards } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getSession, importDemoSession, importLiveSession, listSessions } from "./api";
import { filterEvents, formatAmount, shortenAddress } from "./format";
import type { AgentSnapshot, EventFilters, EventKind, EventStatus, PoolSnapshot, Session, SessionListItem, TimelineEvent } from "./types";

const ALL = "all";
const EVENT_KIND_OPTIONS: Array<EventKind | typeof ALL> = [ALL, "news", "agent_decision", "validation", "transaction", "portfolio_update"];
const STATUS_OPTIONS: Array<EventStatus | typeof ALL> = [ALL, "ok", "confirmed", "pending", "rejected"];

type ActiveTab = "overview" | "charts";

export default function App() {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [filters, setFilters] = useState<EventFilters>({ kind: ALL, status: ALL, poolId: ALL, agentId: ALL });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");

  useEffect(() => {
    void refreshSessions();
  }, []);

  const visibleEvents = useMemo(() => filterEvents(session?.events ?? [], filters).reverse(), [filters, session]);
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

  async function loadLiveSession() {
    setLoading(true);
    setError(null);
    try {
      const imported = await importLiveSession();
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
      setError(err instanceof Error ? err.message : "Failed to import live session");
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
      {session ? <NewsTicker events={session.events} /> : null}
      <header className="topbar">
        <div>
          <p className="eyebrow">On-chain stock agents</p>
          <h1>{session?.name ?? "Dashboard"}</h1>
          <p className="meta">
            {session ? `${session.source} / ${session.network ?? "local"} / ${session.scenarioPath ?? "scenario unavailable"}` : "No active session"}
          </p>
        </div>
        <div className="toolbar">
          <button type="button" onClick={loadLiveSession} disabled={loading} title="Read current state from the deployed contracts">
            <Wifi size={16} aria-hidden="true" />
            Import Live
          </button>
          {session ? (
            <button type="button" onClick={loadSampleSession} disabled={loading}>
              <Download size={16} aria-hidden="true" />
              Sample session
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
          <nav className="tab-nav" aria-label="Dashboard tabs">
            <button
              type="button"
              className={`tab-btn${activeTab === "overview" ? " active" : ""}`}
              onClick={() => setActiveTab("overview")}
            >
              Overview
            </button>
            <button
              type="button"
              className={`tab-btn${activeTab === "charts" ? " active" : ""}`}
              onClick={() => setActiveTab("charts")}
            >
              <TrendingUp size={15} aria-hidden="true" />
              Token Charts
            </button>
          </nav>
          {activeTab === "overview" ? (
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
          ) : (
            <TokenCharts pools={session.pools} />
          )}
        </>
      ) : (
        <section className="empty-state">
          <Activity size={32} aria-hidden="true" />
          <h2>No sessions loaded</h2>
          <p>Connect to a running Hardhat or Sepolia node to read live contract state, or load a sample run.</p>
          <div className="toolbar" style={{ justifyContent: "center" }}>
            <button type="button" onClick={loadLiveSession} disabled={loading}>
              <Wifi size={16} aria-hidden="true" />
              Import Live
            </button>
            <button type="button" onClick={loadSampleSession} disabled={loading}>
              <Download size={16} aria-hidden="true" />
              Sample session
            </button>
          </div>
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
        <h2>Transactions</h2>
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

function NewsTicker({ events }: { events: TimelineEvent[] }) {
  const latest = [...events].reverse().find((e) => e.kind === "news");
  if (!latest) return null;
  return (
    <div className="news-ticker" role="marquee" aria-label="Latest news">
      <span className="ticker-badge">NEWS</span>
      <div className="ticker-track">
        <span className="ticker-text">{latest.summary}</span>
      </div>
    </div>
  );
}

function TokenCharts({ pools }: { pools: PoolSnapshot[] }) {
  const [selectedPoolId, setSelectedPoolId] = useState(pools[0]?.id ?? "");
  const pool = pools.find((p) => p.id === selectedPoolId) ?? pools[0] ?? null;

  return (
    <section className="token-charts-tab">
      <div className="section-heading">
        <h2>Token Price Charts</h2>
        <select
          value={selectedPoolId}
          onChange={(e) => setSelectedPoolId(e.target.value)}
          className="chart-token-select"
          aria-label="Select token pair"
        >
          {pools.map((p) => (
            <option key={p.id} value={p.id}>
              {p.baseSymbol} / {p.quoteSymbol}
            </option>
          ))}
        </select>
      </div>
      {pool ? <PriceChart pool={pool} /> : <p className="muted">No pool selected.</p>}
    </section>
  );
}

function PriceChart({ pool }: { pool: PoolSnapshot }) {
  const history = pool.priceHistory;

  if (!history || history.length < 2) {
    return (
      <div className="chart-empty">
        <p className="muted">No price history available for this token.</p>
      </div>
    );
  }

  const prices = history.map((p) => {
    try {
      return Number(BigInt(p)) / 1e18;
    } catch {
      return 0;
    }
  });

  const W = 600;
  const H = 200;
  const pad = { top: 20, right: 20, bottom: 32, left: 64 };
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;

  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const range = maxP - minP || maxP * 0.01 || 1;

  const toX = (i: number) => pad.left + (i / (prices.length - 1)) * chartW;
  const toY = (p: number) => pad.top + (1 - (p - minP) / range) * chartH;

  const polylinePoints = prices.map((p, i) => `${toX(i).toFixed(1)},${toY(p).toFixed(1)}`).join(" ");

  const yTicks = [minP, (minP + maxP) / 2, maxP];
  const xStep = Math.max(1, Math.ceil(prices.length / 6));
  const xTicks = prices.map((_, i) => i).filter((i) => i % xStep === 0 || i === prices.length - 1);

  const lastPrice = prices[prices.length - 1];
  const firstPrice = prices[0];
  const isUp = lastPrice >= firstPrice;

  return (
    <div className="chart-card">
      <p className="chart-title">
        {pool.baseSymbol} / {pool.quoteSymbol} — Spot Price History
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="price-chart" aria-label={`Price chart for ${pool.baseSymbol}`}>
        {yTicks.map((tick, i) => {
          const y = toY(tick);
          return (
            <g key={i}>
              <line x1={pad.left} y1={y} x2={W - pad.right} y2={y} stroke="#e2e8eb" strokeWidth="1" />
              <text x={pad.left - 6} y={y} textAnchor="end" dominantBaseline="middle" className="chart-label">
                {tick.toFixed(4)}
              </text>
            </g>
          );
        })}
        {xTicks.map((i) => (
          <text key={i} x={toX(i)} y={H - pad.bottom + 18} textAnchor="middle" className="chart-label">
            T{i + 1}
          </text>
        ))}
        <polyline
          points={polylinePoints}
          fill="none"
          stroke={isUp ? "#246643" : "#8f2418"}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <circle cx={toX(prices.length - 1)} cy={toY(lastPrice)} r="4" fill={isUp ? "#246643" : "#8f2418"} />
      </svg>
      <div className="chart-stats">
        <span>
          Current <strong>{lastPrice.toFixed(4)}</strong>
        </span>
        <span>
          High <strong>{maxP.toFixed(4)}</strong>
        </span>
        <span>
          Low <strong>{minP.toFixed(4)}</strong>
        </span>
        <span className={isUp ? "chart-stat-up" : "chart-stat-down"}>
          Change{" "}
          <strong>
            {isUp ? "+" : ""}
            {((lastPrice / firstPrice - 1) * 100).toFixed(2)}%
          </strong>
        </span>
      </div>
    </div>
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
