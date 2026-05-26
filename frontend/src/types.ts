export type SessionSource = "sample" | "imported" | "mock-demo" | "live-demo";
export type AgentType = "trader" | "lp";
export type EventKind = "news" | "agent_decision" | "validation" | "transaction" | "portfolio_update";
export type EventStatus = "ok" | "rejected" | "pending" | "confirmed";

export type SessionSummary = {
  agentCount: number;
  eventCount: number;
  confirmedTxCount: number;
  rejectedCount: number;
};

export type AgentSnapshot = {
  id: string;
  type: AgentType;
  label: string;
  address: string;
  balances: Record<string, string>;
};

export type PoolSnapshot = {
  id: string;
  baseSymbol: string;
  quoteSymbol: string;
  spotPrice?: string;
  reserveA?: string;
  reserveB?: string;
  feeBps?: number;
  priceHistory?: string[];
};

export type TimelineEvent = {
  id: string;
  tick?: number;
  timestamp?: string;
  kind: EventKind;
  agentId?: string;
  agentType?: AgentType;
  poolId?: string;
  action?: string;
  status?: EventStatus;
  summary: string;
  txHash?: string;
  validationReason?: string;
  portfolioDelta?: Record<string, string>;
};

export type Session = {
  id: string;
  name: string;
  source: SessionSource;
  scenarioPath?: string;
  network?: string;
  createdAt: string;
  updatedAt: string;
  summary: SessionSummary;
  agents: AgentSnapshot[];
  pools: PoolSnapshot[];
  events: TimelineEvent[];
};

export type SessionListItem = Pick<Session, "id" | "name" | "source" | "createdAt" | "updatedAt" | "summary">;

export type EventFilters = {
  kind?: EventKind | "all";
  status?: EventStatus | "all";
  poolId?: string | "all";
  agentId?: string | "all";
};
