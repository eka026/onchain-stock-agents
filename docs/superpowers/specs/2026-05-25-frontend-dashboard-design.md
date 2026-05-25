# Frontend Dashboard Design

Date: 2026-05-25

## Goal

Build a frontend for the on-chain stock agents project that shows what happened during an agent run: news broadcasts, agent decisions, validation outcomes, transactions, current market prices, pool state, and agent portfolios.

The first version will be a hybrid dashboard. It will display replayable session data first, while using an API and data model that can later support starting a demo run from the UI and streaming live updates.

## Selected Direction

Use a Session API plus Timeline UI.

The Python API owns session creation, normalization, and persistence. The React frontend consumes normalized session JSON and renders a timeline-first dashboard. The frontend will not talk directly to Solidity contracts, private keys, or RPC providers.

This keeps the UI stable whether data comes from a sample session, an imported demo result, a mock demo run, a Sepolia run, or future live streaming.

## Architecture

Add two new project areas:

```text
api/
frontend/
```

`api/` is a small FastAPI backend around the existing Python agent and demo code. It exposes session data in a frontend-friendly format and provides a future boundary for running demos.

`frontend/` is a React + Vite + TypeScript dashboard. It calls the Python API, renders sessions, and keeps its internal state focused on UI behavior such as filtering, selected timeline event, and refresh state.

Data flow:

```text
agents/run_demo.py + chain readers
        |
        v
FastAPI session service
        |
        v
Normalized Session JSON
        |
        v
React timeline dashboard
```

## Backend API

Initial endpoints:

```text
GET /health
GET /api/sessions
GET /api/sessions/{session_id}
POST /api/sessions/import-demo
```

MVP behavior:

- `GET /api/sessions` returns available generated or imported sessions.
- `GET /api/sessions/{session_id}` returns the full normalized session for the dashboard.
- `POST /api/sessions/import-demo` creates a session from deterministic demo/sample data without requiring RPC, private keys, or LLM provider setup.

Designed but not required in the first implementation:

```text
POST /api/sessions/run
```

That endpoint will later call `agents.run_demo.run_demo(...)`, store the resulting session, and eventually stream progress through WebSockets or server-sent events.

Backend modules:

```text
api/main.py
api/models.py
api/session_store.py
api/normalizer.py
api/sample_data.py
```

Responsibilities:

- `main.py`: FastAPI app, CORS setup for local frontend development, route registration.
- `models.py`: Pydantic response models for sessions, agents, pools, and timeline events.
- `session_store.py`: local session persistence. Start with in-memory plus JSON-file storage.
- `normalizer.py`: converts demo/run objects into normalized session events.
- `sample_data.py`: creates a deterministic sample session so the UI works with no chain setup.

## Frontend UI

The first screen is the dashboard itself. There is no landing page.

Primary layout: timeline-first command center.

Top band:

- Session selector and status: current session, source, scenario, network, and last updated.
- Key metrics: active agents, event count, confirmed transaction count, rejected action count.
- Controls: load sample/latest session, refresh, and a disabled or future-ready run-demo action.

Main area:

- Left/main column: market overview, compact pool price/reserve cards, then the event timeline.
- Right column: selected event details and agent portfolio summary.
- Timeline rows show tick, event kind, agent, action, pool, status, transaction hash when present, and a short summary.
- Clicking a timeline row updates the details panel.
- Filters cover event kind, agent, pool, and status.

Portfolio area:

- Agent list grouped by trader and LP.
- Each agent shows token balances and recent portfolio deltas when available.
- MVP balances come from session snapshots and portfolio update events.

Visual tone:

- Dense and operational, not marketing-like.
- Restrained colors, compact controls, and status accents only where they communicate state.
- Charts start simple: compact price or reserve cards, with optional sparklines once session history supports them.

## Data Model

Large token amounts must travel over the API as strings to avoid JavaScript precision loss.

Session:

```ts
type Session = {
  id: string;
  name: string;
  source: "sample" | "imported" | "mock-demo" | "live-demo";
  scenarioPath?: string;
  network?: string;
  createdAt: string;
  updatedAt: string;
  summary: {
    agentCount: number;
    eventCount: number;
    confirmedTxCount: number;
    rejectedCount: number;
  };
  agents: AgentSnapshot[];
  pools: PoolSnapshot[];
  events: TimelineEvent[];
};
```

Agent snapshot:

```ts
type AgentSnapshot = {
  id: string;
  type: "trader" | "lp";
  label: string;
  address: string;
  balances: Record<string, string>;
};
```

Pool snapshot:

```ts
type PoolSnapshot = {
  id: string;
  baseSymbol: string;
  quoteSymbol: string;
  spotPrice?: string;
  reserveA?: string;
  reserveB?: string;
  feeBps?: number;
};
```

Timeline event:

```ts
type TimelineEvent = {
  id: string;
  tick?: number;
  timestamp?: string;
  kind: "news" | "agent_decision" | "validation" | "transaction" | "portfolio_update";
  agentId?: string;
  agentType?: "trader" | "lp";
  poolId?: string;
  action?: string;
  status?: "ok" | "rejected" | "pending" | "confirmed";
  summary: string;
  txHash?: string;
  validationReason?: string;
  portfolioDelta?: Record<string, string>;
};
```

The event taxonomy is intentionally compact for the MVP. A future optional `metadata` field can hold raw observations, LLM payloads, receipt data, and policy details without cluttering the main dashboard.

## Error Handling

Backend:

- Missing sessions return `404`.
- Bad imports or bad normalization input return `400`.
- Runtime/demo execution failures later return `500` with a safe summary.
- API responses must not include private keys, provider API keys, RPC URLs with secrets, or raw environment details.
- Session file writes should write to a temp file first, then replace the target JSON file.

Frontend:

- If no sessions exist, show an empty state with a load-sample action.
- Failed API calls show an inline error banner.
- Partial sessions still render the timeline even if pools or portfolio snapshots are incomplete.
- Big integer formatting falls back to raw strings instead of crashing.

## Testing

Backend tests:

- Unit tests for normalizing demo-like results into sessions and timeline events.
- API tests for `GET /health`, `GET /api/sessions`, `GET /api/sessions/{session_id}`, and sample import.
- Serialization test proving large numeric values are returned as strings.

Frontend tests:

- Unit/component tests for summary counts, event filtering, selected-event behavior, and amount formatting.
- Manual verification with the API and Vite dev server: load sample session, select timeline events, filter by status/pool/agent, and refresh.

Existing project checks should continue to pass:

```powershell
python -m pytest
npm test
npm run compile
```

New scripts should be added during implementation:

```text
npm run frontend:dev
npm run frontend:build
npm run api:dev
```

## Initial Implementation Scope

Implement the display-first MVP:

- FastAPI app with health, session list, session detail, and sample import endpoints.
- Local session store.
- Normalized session models.
- Deterministic sample session.
- React/Vite/TypeScript app.
- Timeline-first dashboard.
- Pool overview, agent portfolio summary, filters, selected event details, and refresh.

Defer:

- Starting real demos from the UI.
- WebSocket or server-sent event streaming.
- Raw JSON drawers.
- Direct frontend contract reads.
- Authentication or hosted deployment.

## Open Decisions

No blocking open decisions remain for the display-first MVP. Live demo execution and streaming should be designed in the implementation plan as future extension points, not built into the first slice.
