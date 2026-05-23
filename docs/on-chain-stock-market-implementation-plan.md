# News-Driven Multi-Pool AMM Agent Simulation Implementation Plan

## Goal

Build a reproducible prototype where LLM-based trader and liquidity-provider agents interact with multiple on-chain AMM pools. Trader agents receive raw news broadcasts, infer which market is relevant, and submit swaps. LP agents manage liquidity and collect fees. Solidity contracts remain the final authority for token approvals, swap limits, liquidity limits, fee-withdrawal limits, fees, and atomic settlement.

Core claim:

```text
LLM agents produce market intent. Python validates structure and obvious constraints. Solidity enforces the economic rules.
```

## Architecture

The system uses many simple two-token AMM pools instead of one multi-token pool. Each stock-like token trades against a shared mock USD token:

```text
AAPL / USD  -> AMMPool #1
TSLA / USD  -> AMMPool #2
NVDA / USD  -> AMMPool #3
MSFT / USD  -> AMMPool #4
```

Each pool has its own `LPToken` and `FeeVault`. `FeeVault` intentionally stays simple for the prototype: it accumulates swap fees and lets LPs collect proportional fees subject to policy limits. We are not implementing production-grade reward debt accounting.

The blockchain is the source of truth for reserves, LP balances, token balances, fees, and policy state. Local portfolios are only caches and update after confirmed receipts with expected events.

## Tech Stack

- Solidity `0.8.24`
- OpenZeppelin v5 ERC-20 and ownership primitives
- Hardhat and TypeScript tests
- Python 3.12, Web3.py, pytest, Pydantic, python-dotenv
- Optional LLM providers: OpenAI, Google Gemini, Groq
- Sepolia testnet or local Hardhat node

## On-Chain Components

### `AgentPolicy.sol`

Shared compliance layer for agents.

Responsibilities:

- approve tradable tokens;
- configure trader swap limits and rolling spending windows;
- configure LP liquidity add/remove limits;
- configure LP fee-withdrawal limits;
- authorize recorder contracts, usually pools and fee vaults;
- expose validation functions that revert on policy violations.

Important functions:

```solidity
setTokenApproval(address token, bool approved)
setTraderPolicy(address trader, bool enabled, uint256 maxSwapAmount, uint256 spendingLimit, uint256 windowDuration)
setLPPolicy(address lp, bool enabled, uint256 maxLiquidityAdd, uint256 maxLiquidityRemove, uint256 maxFeeWithdrawal, uint256 windowDuration)
setRecorder(address recorder, bool approved)

validateSwap(address trader, address tokenIn, uint256 amountIn)
validateLiquidityAdd(address lp, uint256 amountA, uint256 amountB)
validateLiquidityRemove(address lp, uint256 lpShares)
validateFeeWithdrawal(address lp, uint256 amount)

recordSpending(address trader, uint256 amount)
recordFeeWithdrawal(address lp, uint256 amount)
```

### `LPToken.sol`

ERC-20 LP token for one pool. Only the configured pool may mint or burn.

Deployment pattern:

```text
deploy LPToken -> deploy AMMPool -> LPToken.setPool(pool)
```

### `AMMPool.sol`

Two-token constant-product AMM using `x * y = k`.

Responsibilities:

- accept balanced liquidity;
- mint and burn LP shares;
- execute swaps with a configurable fee;
- forward fees to `FeeVault`;
- protect users with `minAmountOut`, `minLpShares`, and `deadline`;
- call `AgentPolicy` before actions and record spending after successful swaps.

Important functions:

```solidity
addLiquidity(uint256 amountA, uint256 amountB, uint256 minLpShares)
removeLiquidity(uint256 lpShares)
swap(address tokenIn, uint256 amountIn, uint256 minAmountOut, uint256 deadline)
spotPrice()
setFeeBps(uint256 newFeeBps)
```

### `FeeVault.sol`

Simple fee accumulator for one pool.

Responsibilities:

- accept fee notifications from the configured pool;
- track total and cumulative fees for token A and token B;
- let LPs collect proportional fees;
- validate and record fee withdrawals through `AgentPolicy`.

Prototype simplification:

```text
Fee claims are proportional to current LP shares and current total supply. This is acceptable for the demo and intentionally not production reward accounting.
```

### `MockERC20.sol`

Demo token used for USD and stock-like assets.

## Off-Chain Components

### `agents/news_feed.py`

Loads raw news and scenario files, then produces deterministic news broadcasts.

Rules:

- news records must contain raw text only;
- no token labels, sentiment labels, impact scores, or trade hints;
- scenario metadata defines available tokens and pools;
- seed-based scheduling makes demos reproducible.

### `agents/schemas.py`

Stores structured agent decisions.

Trader decision:

```json
{
  "action": "SWAP",
  "pool_id": "NVDA-USD",
  "token_in": "USD",
  "amount_in": 1000000000000000000,
  "reason": "The news appears positive for Nvidia, so I am buying NVDA with USD."
}
```

Supported trader actions:

```text
SWAP
HOLD
```

LP decision:

```json
{
  "action": "ADD_LIQUIDITY",
  "pool_id": "NVDA-USD",
  "amount_a": 1000000000000000000,
  "amount_b": 1000000000000000000,
  "reason": "The pool has enough volume to justify adding liquidity."
}
```

Supported LP actions:

```text
ADD_LIQUIDITY
REMOVE_LIQUIDITY
COLLECT_FEES
HOLD
```

### `agents/config.py`

Loads RPC URLs, contract addresses, wallet keys, model assignments, and optional provider keys from `.env`.

Trader and LP wallets are paired by index:

```text
TRADER_PRIVATE_KEYS <-> TRADER_MODELS
LP_PRIVATE_KEYS     <-> LP_MODELS
```

### Planned Python Modules

These should be implemented next:

```text
agents/llm.py          provider routing and mock LLM client
agents/chain.py        Web3 contracts, reads, tx submission, receipt verification
agents/portfolio.py    token/LP balance cache with pending execution state
agents/trader_agent.py trader observe/decide/execute/verify loop
agents/lp_agent.py     LP observe/decide/execute/verify loop
agents/run_demo.py     deterministic end-to-end demo runner
```

## Scenario Files

Raw news:

```text
data/news.json
```

Reproducible demo scenario:

```text
data/scenarios/demo.json
```

The scenario should define:

- seed;
- news file path;
- broadcast interval range;
- max news events;
- token metadata;
- shared policy address;
- pool metadata, including pool, LP token, and fee vault addresses.

The scenario may tell agents which markets exist. It must not tell agents how to interpret the news.

## Deployment Model

For each pair such as `NVDA-USD`, deploy:

```text
MockERC20 USD      shared across pools
MockERC20 NVDA
AgentPolicy       shared across pools
LPToken           one per pool
FeeVault          one per pool
AMMPool           one per pool
```

Then wire:

```text
LPToken.setPool(pool)
FeeVault.setPool(pool)
AgentPolicy.setTokenApproval(token, true)
AgentPolicy.setTraderPolicy(...)
AgentPolicy.setLPPolicy(...)
AgentPolicy.setRecorder(pool, true)
AgentPolicy.setRecorder(vault, true)
```

For a single-pool local smoke test, `scripts/deploy.ts` may deploy one token pair. The multi-pool demo runner can either use multiple deployments or a scenario file with deployed addresses.

## Demo Requirements

The demo should show:

1. Deterministic news broadcast to all traders.
2. Trader agent parses raw news and chooses `HOLD` or `SWAP`.
3. Successful swap emits `Swap`.
4. LP agent adds liquidity and emits `LiquidityAdded`.
5. LP agent collects fees and emits `FeesCollected`.
6. LP agent removes liquidity and emits `LiquidityRemoved`.
7. Oversized swap is rejected by `AgentPolicy`.
8. Unapproved token swap is rejected by `AgentPolicy`.
9. Disabled LP liquidity action is rejected by `AgentPolicy`.
10. Reverted or rejected actions do not mutate local confirmed portfolio state.

## Implementation Phases

### Phase 1: Contract Core

#### Task 1.1: Policy Contract

Files:

```text
contracts/AgentPolicy.sol
test/AgentPolicy.test.ts
```

- [x] Approve and reject tradable tokens.
- [x] Configure trader policies.
- [x] Configure LP policies.
- [x] Validate swaps.
- [x] Validate liquidity add/remove.
- [x] Validate fee withdrawals.
- [x] Restrict usage recording to authorized recorders.
- [x] Test owner-only configuration.
- [x] Test rolling spending and fee-withdrawal windows.

Verification:

```powershell
npm test -- test/AgentPolicy.test.ts
```

#### Task 1.2: LP Token

Files:

```text
contracts/LPToken.sol
test/LPToken.test.ts
```

- [x] Implement ERC-20 LP token.
- [x] Allow pool to be set once.
- [x] Reject zero pool address.
- [x] Restrict minting to the pool.
- [x] Restrict burning to the pool.
- [x] Test non-pool mint/burn rejection.

Verification:

```powershell
npm test -- test/LPToken.test.ts
```

#### Task 1.3: AMM Pool

Files:

```text
contracts/AMMPool.sol
test/AMMPool.test.ts
```

- [x] Implement first liquidity add with `sqrt(amountA * amountB)`.
- [x] Implement proportional subsequent liquidity add.
- [x] Enforce balanced liquidity ratio after initialization.
- [x] Implement `minLpShares` protection.
- [x] Implement liquidity removal and LP burn.
- [x] Implement token A to token B swaps.
- [x] Implement token B to token A swaps.
- [x] Implement configurable fee basis points.
- [x] Forward fees to `FeeVault`.
- [x] Implement `minAmountOut` slippage protection.
- [x] Implement swap `deadline`.
- [x] Record trader spending after successful swap.
- [x] Emit `LiquidityAdded`, `LiquidityRemoved`, `Swap`, and `FeeBpsUpdated`.

Verification:

```powershell
npm test -- test/AMMPool.test.ts
```

#### Task 1.4: Fee Vault

Files:

```text
contracts/FeeVault.sol
test/FeeVault.test.ts
```

- [x] Allow pool to be set once.
- [x] Accept fee notifications only from pool.
- [x] Track token A fees.
- [x] Track token B fees.
- [x] Track cumulative fees for simple proportional claiming.
- [x] Let LPs collect proportional fees.
- [x] Validate fee withdrawal with `AgentPolicy`.
- [x] Record fee withdrawal after successful collection.
- [x] Emit `PoolSet`, `FeeNotified`, and `FeesCollected`.

Verification:

```powershell
npm test -- test/FeeVault.test.ts
```

#### Task 1.5: Contract Integration Test

Files:

```text
test/IntegrationMarket.test.ts
```

- [x] Deploy `MockERC20` USD token.
- [x] Deploy at least two stock-like `MockERC20` tokens.
- [x] Deploy shared `AgentPolicy`.
- [x] Deploy one `LPToken`, `FeeVault`, and `AMMPool` per stock/USD pair.
- [x] Wire every `LPToken.setPool(pool)`.
- [x] Wire every `FeeVault.setPool(pool)`.
- [x] Approve all tradable tokens in policy.
- [x] Configure trader and LP policies.
- [x] Authorize every pool and vault as recorders.
- [x] Fund LP and trader wallets.
- [x] Approve pool token transfers.
- [x] Add liquidity to at least two pools.
- [x] Execute a successful swap in one pool.
- [x] Collect fees from the matching vault.
- [x] Remove liquidity.
- [x] Assert oversized swap rejection.
- [x] Assert unapproved token rejection.
- [x] Assert disabled LP rejection.

Verification:

```powershell
npm test -- test/IntegrationMarket.test.ts
```

#### Phase 1 Verification

Run after all Phase 1 tasks:

```powershell
npm run compile
npm test
```

### Phase 2: News and Decision Layer

#### Task 2.1: Raw News Loader

Files:

```text
agents/news_feed.py
data/news.json
test/test_news_feed.py
```

- [x] Load news records from JSON.
- [x] Accept only `id`, `headline`, and `body`.
- [x] Reject interpretation fields such as `token`, `sentiment`, and `impact`.
- [x] Keep news raw and unlabeled.

Verification:

```powershell
python -m pytest test/test_news_feed.py
```

#### Task 2.2: Scenario Loader

Files:

```text
agents/news_feed.py
data/scenarios/demo.json
test/test_news_feed.py
```

- [x] Load scenario JSON.
- [x] Validate seed and interval settings.
- [x] Validate token metadata.
- [x] Validate pool metadata.
- [x] Reject pools that reference unknown token symbols.
- [x] Keep pool metadata separate from news interpretation.

Verification:

```powershell
python -m pytest test/test_news_feed.py
```

#### Task 2.3: Deterministic News Scheduler

Files:

```text
agents/news_feed.py
test/test_news_feed.py
```

- [x] Use scenario seed for reproducible ordering.
- [x] Generate deterministic interval ticks.
- [x] Respect `max_events`.
- [x] Broadcast the same scheduled news item to all traders.

Verification:

```powershell
python -m pytest test/test_news_feed.py
```

#### Task 2.4: Trader Decision Schema

Files:

```text
agents/schemas.py
test/test_schemas.py
```

- [x] Support `HOLD`.
- [x] Support `SWAP`.
- [x] Require positive `amount_in` for swaps.
- [x] Validate known `pool_id`.
- [x] Validate `token_in` belongs to the selected pool.
- [x] Add optional `max_slippage_bps` if agents should control slippage.
- [x] Add optional `deadline_seconds` if agents should control deadline.

Verification:

```powershell
python -m pytest test/test_schemas.py
```

#### Task 2.5: LP Decision Schema

Files:

```text
agents/schemas.py
test/test_schemas.py
```

- [x] Support `HOLD`.
- [x] Support `ADD_LIQUIDITY`.
- [x] Support `REMOVE_LIQUIDITY`.
- [x] Support `COLLECT_FEES`.
- [x] Require positive token amounts for liquidity add.
- [x] Require positive LP shares for remove and fee collection.
- [x] Validate known `pool_id`.
- [x] Add optional `min_lp_shares` if agents should control LP slippage.

Verification:

```powershell
python -m pytest test/test_schemas.py
```

#### Task 2.6: Config Loader

Files:

```text
agents/config.py
test/test_config.py
.env.example
```

- [x] Load RPC URL.
- [x] Load trader private keys and model assignments.
- [x] Load LP private keys and model assignments.
- [x] Reject trader key/model length mismatch.
- [x] Reject LP key/model length mismatch.
- [x] Load optional provider API keys.
- [x] Decide whether pool addresses live in `.env`, scenario JSON, or both.

Decision:

```text
.env stores RPC, wallet keys, model assignments, provider keys, and SCENARIO_PATH.
Scenario JSON stores deployed policy, token, pool, LP token, and vault addresses.
```

Verification:

```powershell
python -m pytest test/test_config.py
```

#### Phase 2 Verification

Run after all Phase 2 tasks:

```powershell
python -m pytest test/test_news_feed.py test/test_schemas.py test/test_config.py
```

### Phase 3: Python Execution Layer

#### Task 3.1: Contract Registry

Files:

```text
agents/chain.py
test/test_chain_contracts.py
```

- [x] Load ABI files from `agents/abis`.
- [x] Build Web3 contract instances for `AgentPolicy`, `AMMPool`, `LPToken`, and `FeeVault`.
- [x] Build Web3 contract instances for `MockERC20`.
- [x] Resolve pool contracts from scenario `pool_id`.
- [x] Resolve token symbols to addresses.
- [x] Fail clearly when an ABI or address is missing.

Verification:

```powershell
python -m pytest test/test_chain_contracts.py
```

#### Task 3.2: Chain Read Helpers

Files:

```text
agents/chain.py
test/test_chain_reads.py
```

- [x] Read ERC-20 token balances.
- [x] Read LP token balances.
- [x] Read pool reserves.
- [x] Read spot price.
- [x] Read vault fee totals.
- [x] Read token approval status.
- [x] Read trader policy state.
- [x] Read LP policy state.

Verification:

```powershell
python -m pytest test/test_chain_reads.py
```

#### Task 3.3: Local Decision Validation

Files:

```text
agents/chain.py
test/test_local_validation.py
```

- [x] Reject unknown pool IDs.
- [x] Reject token symbols not in selected pool.
- [x] Reject missing token allowance before submitting.
- [x] Reject swaps that exceed locally observed policy limits.
- [x] Reject liquidity actions that exceed locally observed LP policy limits.
- [x] Keep smart contracts as final authority even if local validation passes.

Verification:

```powershell
python -m pytest test/test_local_validation.py
```

#### Task 3.4: Transaction Builder and Submitter

Files:

```text
agents/chain.py
test/test_chain_transactions.py
```

- [x] Build `AMMPool.swap(...)` transactions.
- [x] Build `AMMPool.addLiquidity(...)` transactions.
- [x] Build `AMMPool.removeLiquidity(...)` transactions.
- [x] Build `FeeVault.collectFees(...)` transactions.
- [x] Sign transactions with the selected wallet.
- [x] Submit transactions through Web3.
- [x] Return transaction hashes without mutating local portfolio state.

Verification:

```powershell
python -m pytest test/test_chain_transactions.py
```

#### Task 3.5: Receipt and Event Verification

Files:

```text
agents/chain.py
test/test_chain_receipts.py
```

- [x] Define `ExecutionResult`.
- [x] Return `CONFIRMED` for successful receipts with expected events.
- [x] Return `REJECTED` for reverted receipts.
- [x] Return `REJECTED` for successful receipts missing expected events.
- [x] Return `PENDING` for timeout or missing receipts.
- [x] Extract event data needed for portfolio updates.

Verification:

```powershell
python -m pytest test/test_chain_receipts.py
```

### Phase 4: Agent Services

#### Task 4.1: Portfolio Cache

Files:

```text
agents/portfolio.py
test/test_portfolio.py
```

- [x] Record pending actions by transaction hash.
- [x] Apply token balance deltas only after confirmation.
- [x] Support swaps.
- [x] Support liquidity add.
- [x] Support liquidity remove.
- [x] Support fee collection.
- [x] Discard rejected actions without changing confirmed balances.
- [x] Treat unknown confirmation as an error.

Verification:

```powershell
python -m pytest test/test_portfolio.py
```

#### Task 4.2: Mock LLM Client

Files:

```text
agents/llm.py
test/test_llm.py
```

- [x] Implement deterministic mock responses.
- [x] Support trader decision responses.
- [x] Support LP decision responses.
- [x] Support invalid JSON test responses.
- [x] Ensure tests never call paid APIs.

Verification:

```powershell
python -m pytest test/test_llm.py
```

#### Task 4.3: Optional Live LLM Routing

Files:

```text
agents/llm.py
test/test_llm.py
requirements.txt
```

- [ ] Route OpenAI model names to OpenAI client.
- [ ] Route Gemini model names to Google client.
- [ ] Route Llama/Groq model names to Groq client.
- [ ] Fail clearly when a required provider key is missing.
- [ ] Keep live calls out of unit tests.

Verification:

```powershell
python -m pytest test/test_llm.py
```

#### Task 4.4: Trader Agent

Files:

```text
agents/trader_agent.py
test/test_trader_agent.py
```

- [ ] Load trader config by `--index`.
- [ ] Observe current news.
- [ ] Observe available pools and token metadata.
- [ ] Observe balances, reserves, spot price, and policy state.
- [ ] Build compact LLM prompt.
- [ ] Parse `TraderDecision`.
- [ ] Execute `HOLD` as no-op.
- [ ] Execute `SWAP` through chain layer.
- [ ] Verify `Swap` event.
- [ ] Update portfolio only after confirmation.
- [ ] Support `--once`.
- [ ] Support `--interval`.

Verification:

```powershell
python -m pytest test/test_trader_agent.py
python -m agents.trader_agent --index 0 --once --llm mock
```

#### Task 4.5: LP Agent

Files:

```text
agents/lp_agent.py
test/test_lp_agent.py
```

- [ ] Load LP config by `--index`.
- [ ] Observe pool reserves and prices.
- [ ] Observe LP balances and accumulated fees.
- [ ] Observe LP policy state.
- [ ] Build compact LLM prompt.
- [ ] Parse `LPDecision`.
- [ ] Execute `HOLD` as no-op.
- [ ] Execute `ADD_LIQUIDITY`.
- [ ] Execute `REMOVE_LIQUIDITY`.
- [ ] Execute `COLLECT_FEES`.
- [ ] Verify expected events.
- [ ] Update portfolio only after confirmation.
- [ ] Support `--once`.
- [ ] Support `--interval`.

Verification:

```powershell
python -m pytest test/test_lp_agent.py
python -m agents.lp_agent --index 0 --once --llm mock
```

#### Task 4.6: Demo Runner

Files:

```text
agents/run_demo.py
test/test_run_demo.py
```

- [ ] Load scenario and news feed.
- [ ] Initialize one LP agent and at least two trader agents.
- [ ] Add initial liquidity.
- [ ] Broadcast deterministic news events.
- [ ] Run trader decisions for each broadcast.
- [ ] Collect fees after swaps.
- [ ] Remove liquidity.
- [ ] Trigger negative policy scenarios.
- [ ] Print final confirmed portfolios.
- [ ] Support `--llm mock`.
- [ ] Support `--scenario`.

Expected commands:

```powershell
python -m agents.trader_agent --index 0 --once
python -m agents.lp_agent --index 0 --once
python -m agents.run_demo --scenario data/scenarios/demo.json --llm mock
```

### Phase 5: End-to-End Demo

#### Task 5.1: Local Smoke Demo

Files:

```text
README.md
docs/demo-checklist.md
```

- [ ] Start local Hardhat node.
- [ ] Deploy one token pair with `scripts/deploy.ts`.
- [ ] Export ABIs.
- [ ] Run one LP action.
- [ ] Run one trader action.
- [ ] Verify events and local portfolio output.

Verification:

```powershell
npm run node
npm run deploy:local
npm run export:abis
python -m agents.run_demo --scenario data/scenarios/demo.json --llm mock
```

#### Task 5.2: Multi-Pool Scenario Demo

Files:

```text
data/scenarios/demo.json
docs/demo-checklist.md
```

- [ ] Deploy or configure at least two stock/USD pools.
- [ ] Record all token and pool addresses in scenario metadata.
- [ ] Broadcast the same raw news item to all traders.
- [ ] Show one trader choosing a relevant pool.
- [ ] Show another trader choosing `HOLD` or a different pool.
- [ ] Verify swaps occur only in selected pools.
- [ ] Verify fee accumulation in the selected pool vault.

#### Task 5.3: Negative Scenario Demo

Files:

```text
agents/run_demo.py
docs/demo-checklist.md
```

- [ ] Demonstrate oversized swap rejection.
- [ ] Demonstrate unapproved token rejection.
- [ ] Demonstrate disabled trader rejection.
- [ ] Demonstrate disabled LP rejection.
- [ ] Demonstrate fee-withdrawal limit rejection.
- [ ] Show rejected transactions do not update confirmed portfolio state.

#### Task 5.4: README Reproduction Pass

Files:

```text
README.md
docs/demo-checklist.md
```

- [ ] README lists setup commands.
- [ ] README lists local demo commands.
- [ ] README explains scenario/news files.
- [ ] README explains one-pool smoke deployment vs multi-pool demo.
- [ ] Demo checklist can be followed from a fresh clone.

## Evaluation Criteria

The project is complete when:

- contracts enforce approved tokens, swap limits, spending limits, liquidity limits, fee-withdrawal limits, and atomic settlement;
- swaps follow the constant-product formula with configurable fees;
- fees accumulate in a simple `FeeVault` and can be collected by LPs;
- LLM outputs are structured and treated as intent, not authority;
- news data is raw and unlabeled;
- agents can select among multiple pools using scenario metadata;
- local portfolio state updates only after confirmed receipts and expected events;
- tests use mock LLM clients and never require paid API calls;
- the demo is reproducible from a fresh clone.

## Notes

- Keep economic authority in Solidity.
- Keep `FeeVault` simple for this prototype.
- Do not put token labels, sentiment, impact scores, or trade hints in news records.
- Prefer many two-token pools over a new multi-token AMM contract.
- Emit events for every important state transition so agents can verify outcomes.
