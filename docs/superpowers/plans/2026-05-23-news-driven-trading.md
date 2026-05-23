# News-Driven Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible news-driven trading layer where raw news is broadcast to all trader agents and decisions can select among multiple two-token pools.

**Architecture:** Keep the existing Solidity AMM unchanged and model many markets as multiple two-token pools against a shared quote token. Add Python modules for raw news validation, seeded scheduling, scenario loading, and multi-pool trader decision validation.

**Tech Stack:** Python 3.12, pytest, Pydantic v2, dataclasses, existing `agents/` package.

---

### Task 1: News and Scenario Models

**Files:**
- Create: `agents/news_feed.py`
- Test: `test/test_news_feed.py`

- [ ] Write tests for raw news loading that accepts only `id`, `headline`, and `body`.
- [ ] Run `pytest test/test_news_feed.py -v` and verify it fails because `agents.news_feed` is missing.
- [ ] Implement `NewsItem`, `TokenInfo`, `PoolInfo`, and `Scenario` Pydantic models.
- [ ] Run `pytest test/test_news_feed.py -v` and verify the raw schema tests pass.

### Task 2: Deterministic News Dispatcher

**Files:**
- Modify: `agents/news_feed.py`
- Test: `test/test_news_feed.py`

- [ ] Write tests proving the same seed produces the same schedule and all traders receive the same news item at the same tick.
- [ ] Run `pytest test/test_news_feed.py -v` and verify the dispatcher tests fail because the dispatcher is missing.
- [ ] Implement deterministic scheduling with `random.Random(seed)`.
- [ ] Run `pytest test/test_news_feed.py -v` and verify all news feed tests pass.

### Task 3: Multi-Pool Trader Decision Validation

**Files:**
- Create: `agents/schemas.py`
- Test: `test/test_schemas.py`

- [ ] Write tests for valid `HOLD`, valid `SWAP`, unknown pool rejection, invalid `token_in` rejection, and non-positive swap amount rejection.
- [ ] Run `pytest test/test_schemas.py -v` and verify it fails because `agents.schemas` is missing.
- [ ] Implement `TraderDecision` and `validate_trader_decision`.
- [ ] Run `pytest test/test_schemas.py -v` and verify schema tests pass.

### Task 4: Sample Data

**Files:**
- Create: `data/news.json`
- Create: `data/scenarios/demo.json`

- [ ] Add raw news records with no token, sentiment, impact, or trade hint fields.
- [ ] Add a reproducible scenario with token and pool metadata.
- [ ] Run `pytest test/test_news_feed.py test/test_schemas.py -v`.

### Task 5: Full Verification

**Files:**
- No code changes.

- [ ] Run `python -m pytest`.
- [ ] Run `python -m compileall agents`.
- [ ] Report exact verification results.

