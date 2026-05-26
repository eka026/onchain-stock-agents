# Frontend Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the display-first hybrid dashboard: a FastAPI session API plus a React/Vite/TypeScript timeline UI for agent run sessions.

**Architecture:** The Python API owns normalized sessions, sample data, and local persistence. The React frontend consumes the API and renders a timeline-first operations dashboard with filters, selected-event details, pool overview, and agent portfolios. The UI does not read contracts, RPC settings, or private keys directly.

**Tech Stack:** Python, FastAPI, Pydantic v2, pytest, React, Vite, TypeScript, CSS.

---

## File Structure

- Create `api/__init__.py`: package marker.
- Create `api/models.py`: Pydantic models for `TimelineEvent`, `AgentSnapshot`, `PoolSnapshot`, `SessionSummary`, `Session`, and `SessionListItem`.
- Create `api/sample_data.py`: deterministic sample session builder.
- Create `api/session_store.py`: JSON-file-backed session store with atomic writes.
- Create `api/main.py`: FastAPI app, CORS, health route, session routes.
- Create `test/test_dashboard_api.py`: backend model/store/API tests.
- Modify `requirements.txt`: add FastAPI and Uvicorn.
- Modify `package.json`: add frontend scripts and React/Vite dependencies.
- Create `frontend/index.html`: Vite entry HTML.
- Create `frontend/tsconfig.json`: frontend TypeScript config.
- Create `frontend/src/main.tsx`: React entry point.
- Create `frontend/src/App.tsx`: dashboard composition.
- Create `frontend/src/api.ts`: typed API client.
- Create `frontend/src/types.ts`: TypeScript mirrors of API models.
- Create `frontend/src/format.ts`: amount/address formatting helpers.
- Create `frontend/src/App.css`: dashboard styles.
- Create `frontend/src/App.test.ts`: frontend unit tests for filtering and formatting helpers.

## Task 1: Backend Session Models

**Files:**
- Create: `api/__init__.py`
- Create: `api/models.py`
- Create/modify: `test/test_dashboard_api.py`

- [ ] **Step 1: Write failing model serialization tests**

Add tests that validate big integer values are serialized as strings and summary counts are represented explicitly.

Run:

```powershell
python -m pytest test/test_dashboard_api.py -q
```

Expected: fail because `api.models` does not exist.

- [ ] **Step 2: Implement Pydantic models**

Create models with literal enums matching the design spec. Amount-like values must be strings in public models.

- [ ] **Step 3: Run backend model tests**

Run:

```powershell
python -m pytest test/test_dashboard_api.py -q
```

Expected: model tests pass.

## Task 2: Sample Session and Store

**Files:**
- Create: `api/sample_data.py`
- Create: `api/session_store.py`
- Modify: `test/test_dashboard_api.py`

- [ ] **Step 1: Write failing tests for sample data and persistence**

Tests should assert that `build_sample_session()` includes agents, pools, events, confirmed transaction count, rejected count, and string token amounts. Store tests should save and reload a session from a temporary directory.

Run:

```powershell
python -m pytest test/test_dashboard_api.py -q
```

Expected: fail because sample/store modules do not exist.

- [ ] **Step 2: Implement deterministic sample session**

Create one sample session with:

- Two traders and one LP.
- Two pools.
- News, LP liquidity, trader decision, validation, transaction, rejected validation, and portfolio update events.

- [ ] **Step 3: Implement JSON session store**

Implement `SessionStore` with `list_sessions()`, `get_session(session_id)`, and `save_session(session)`. Use temp-file-plus-replace writes.

- [ ] **Step 4: Run sample/store tests**

Run:

```powershell
python -m pytest test/test_dashboard_api.py -q
```

Expected: all backend tests pass so far.

## Task 3: FastAPI Routes

**Files:**
- Create: `api/main.py`
- Modify: `requirements.txt`
- Modify: `test/test_dashboard_api.py`

- [ ] **Step 1: Write failing API tests**

Tests should cover:

- `GET /health`
- empty `GET /api/sessions`
- `POST /api/sessions/import-demo`
- `GET /api/sessions/{session_id}`
- missing session returns `404`

Run:

```powershell
python -m pytest test/test_dashboard_api.py -q
```

Expected: fail because FastAPI app/routes do not exist or dependencies are missing.

- [ ] **Step 2: Add backend dependencies**

Add `fastapi` and `uvicorn` to `requirements.txt`.

- [ ] **Step 3: Implement FastAPI app**

Create `create_app(store: SessionStore | None = None) -> FastAPI` for tests, plus module-level `app = create_app()`. Add CORS for local Vite development.

- [ ] **Step 4: Run API tests**

Run:

```powershell
python -m pytest test/test_dashboard_api.py -q
```

Expected: all dashboard API tests pass.

## Task 4: Frontend Package and Pure Helpers

**Files:**
- Modify: `package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/format.ts`
- Create: `frontend/src/App.test.ts`

- [ ] **Step 1: Add failing frontend helper tests**

Tests should validate amount formatting, address shortening, and event filtering.

Run:

```powershell
npm run frontend:test -- --run
```

Expected: fail because frontend dependencies/files do not exist yet.

- [ ] **Step 2: Add frontend dependencies and scripts**

Add React, Vite, TypeScript, Vitest, and React plugin configuration through `package.json` scripts:

```json
"api:dev": "uvicorn api.main:app --reload --port 8000",
"frontend:dev": "vite --host 127.0.0.1 --port 5173 frontend",
"frontend:build": "vite build frontend",
"frontend:test": "vitest --config frontend/vitest.config.ts"
```

- [ ] **Step 3: Implement types and helper functions**

Implement TypeScript types matching `api/models.py`, plus formatting/filtering helpers.

- [ ] **Step 4: Run frontend helper tests**

Run:

```powershell
npm run frontend:test -- --run
```

Expected: frontend helper tests pass.

## Task 5: React Timeline Dashboard

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.css`
- Modify: `frontend/src/App.test.ts`

- [ ] **Step 1: Write failing component tests**

Tests should assert that the dashboard renders an empty state, imports the sample session, displays timeline rows, filters by status, and updates selected-event details.

Run:

```powershell
npm run frontend:test -- --run
```

Expected: fail because React app components do not exist.

- [ ] **Step 2: Implement API client**

Implement `listSessions()`, `getSession(id)`, and `importDemoSession()` using `fetch` and `VITE_API_BASE_URL || http://127.0.0.1:8000`.

- [ ] **Step 3: Implement dashboard components**

Build `App.tsx` with session loading, sample import, filters, selected event state, metrics, pool cards, timeline, details panel, and agent portfolios.

- [ ] **Step 4: Implement dashboard CSS**

Use a compact operations-console layout with responsive constraints. Avoid card nesting beyond repeated pool/agent/event items.

- [ ] **Step 5: Run frontend tests**

Run:

```powershell
npm run frontend:test -- --run
```

Expected: all frontend tests pass.

## Task 6: Integration Verification

**Files:**
- Modify if needed: `README.md`

- [ ] **Step 1: Run backend tests**

Run:

```powershell
python -m pytest test/test_dashboard_api.py -q
```

Expected: pass.

- [ ] **Step 2: Run existing Python tests**

Run:

```powershell
python -m pytest
```

Expected: pass.

- [ ] **Step 3: Run contract tests and compile**

Run:

```powershell
npm test
npm run compile
```

Expected: pass.

- [ ] **Step 4: Build frontend**

Run:

```powershell
npm run frontend:build
```

Expected: pass and emit `frontend/dist`.

- [ ] **Step 5: Start local API and frontend for manual check**

Run API and Vite dev servers. Open the frontend, load/import the sample session, select timeline events, and verify filters and details panels behave correctly.

## Self-Review

- Spec coverage: backend session API, sample/import data, React timeline UI, compact event log, filters, selected details, portfolio and pool summaries, error handling, and tests are covered.
- Placeholder scan: no `TBD`, `TODO`, or undefined future-only task is needed for MVP.
- Type consistency: Python and TypeScript models use the same names and string-valued token amounts.
