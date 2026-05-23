# On-Chain AMM Agent Simulation Implementation Plan

**Goal:** Build a reproducible prototype where deployed LLM-based liquidity provider (LP) and trader agents interact with an on-chain Automated Market Maker (AMM) built in Solidity. The AMM enforces swap fees, spending limits, liquidity limits, and fee-withdrawal limits. Local portfolio state updates only after confirmed on-chain receipts.

**Architecture:** The blockchain is the source of truth for reserves, LP token balances, swap fees, and agent policy state. Each LLM agent runs as an off-chain service with its own wallet, observes chain state through RPC, asks a low-cost LLM API for a structured decision, validates that decision locally, submits transactions through Web3, and updates local state only after confirmed receipts and expected events.

**Tech Stack:** Solidity 0.8.24, Hardhat, TypeScript tests, OpenZeppelin v5, Python 3.12, Web3.py, pytest, Pydantic, python-dotenv, multiple LLM providers (OpenAI, Google Gemini, Groq) with per-trader model assignment. Contracts deployed on Sepolia testnet via Remix IDE.

---

## Requirements

- Trader agents represent market participants. They run as LLM-backed services that observe the AMM spot price, their token balances, policy state, and their own portfolios, then submit swaps.
- LP agents represent liquidity providers. They run as LLM-backed services that add or remove liquidity and collect accumulated swap fees from the FeeVault.
- Smart contracts enforce approved tokens, maximum swap sizes, per-trader spending limits, per-LP liquidity and fee-withdrawal limits, and atomic settlement.
- RPC and wallet infrastructure prepares, signs, submits, and confirms transactions.
- LLM outputs are advisory intent only. They must be parsed as structured decisions, validated by local code, and enforced by smart contracts.
- Agents must be deployable as separate long-running processes, not only one-shot demo functions.
- Local portfolio state is not authoritative and must update only after confirmed on-chain execution.
- Reverted transactions must not corrupt local portfolio state.
- The demo must show: successful swap, successful liquidity add/remove, fee collection, oversized swap rejection, unauthorized token rejection, LP-disabled rejection, and recovery from a revert.

## Repository Layout

```text
contracts/
  AgentPolicy.sol
  LPToken.sol
  AMMPool.sol
  FeeVault.sol
  test/
    MockERC20.sol
scripts/
  deploy.ts          (reference only — deploy via Remix IDE)
  export_abis.ts
test/
  AgentPolicy.test.ts
  LPToken.test.ts
  AMMPool.test.ts
  FeeVault.test.ts
  IntegrationMarket.test.ts
  test_portfolio.py
  test_schemas.py
  test_chain_receipts.py
  test_agents_with_mock_llm.py
agents/
  __init__.py
  config.py
  llm.py
  schemas.py
  chain.py
  portfolio.py
  lp_agent.py
  trader_agent.py
  run_demo.py
  abis/
    AgentPolicy.json
    LPToken.json
    AMMPool.json
    FeeVault.json
docs/
  on-chain-stock-market-implementation-plan.md
  demo-checklist.md
hardhat.config.ts
package.json
requirements.txt
pytest.ini
README.md
```

---

## Milestone 1: Project Scaffolding

### Task 1: Initialize Hardhat and Python Tooling

**Files:**
- Create: `package.json`
- Create: `hardhat.config.ts`
- Create: `requirements.txt`
- Create: `pytest.ini`
- Modify: `README.md`

- [x] Create `package.json` with scripts:

```json
{
  "name": "onchain-stock-agents",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "compile": "hardhat compile",
    "test": "hardhat test",
    "node": "hardhat node",
    "deploy:local": "hardhat run scripts/deploy.ts --network localhost",
    "deploy:sepolia": "hardhat run scripts/deploy.ts --network sepolia",
    "export:abis": "hardhat compile && hardhat run scripts/export_abis.ts"
  },
  "devDependencies": {
    "@nomicfoundation/hardhat-toolbox": "^5.0.0",
    "hardhat": "^2.22.0",
    "typescript": "^5.4.0"
  },
  "dependencies": {
    "@openzeppelin/contracts": "^5.0.0"
  }
}
```

- [x] Create `hardhat.config.ts`:

```ts
import { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";

const config: HardhatUserConfig = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 }
    }
  },
  networks: {
    hardhat: {},
    localhost: { url: "http://127.0.0.1:8545" },
    sepolia: {
      url: process.env.SEPOLIA_RPC_URL ?? "",
      accounts: process.env.DEPLOYER_PRIVATE_KEY ? [process.env.DEPLOYER_PRIVATE_KEY] : []
    }
  }
};

export default config;
```

- [x] Create `requirements.txt`:

```text
web3==6.20.1
pytest==8.2.2
python-dotenv==1.0.1
pydantic==2.8.2
openai==1.40.0
google-generativeai==0.8.3
groq==0.11.0
```

- [x] Create `pytest.ini` (disables the broken web3 pytest plugin, adds project root to path):

```ini
[pytest]
addopts = -p no:pytest_ethereum
pythonpath = .
```

- [x] Install dependencies:

```powershell
npm install
python -m pip install -r requirements.txt
```

- [x] Verify scaffolding:

```powershell
npm run compile
```

Expected: Hardhat compiles successfully or reports nothing to compile.

---

## Milestone 2: Core Smart Contracts

### Task 2: Implement `AgentPolicy.sol`

**Responsibility:** Enforce autonomous-agent constraints for the AMM: approved swap tokens, per-trader swap limits with rolling spending windows, per-LP liquidity and fee-withdrawal limits with rolling windows, and authorized recorders.

**Files:**
- Create: `contracts/AgentPolicy.sol`
- Create: `test/AgentPolicy.test.ts`

- [x] Write tests for token approval, validateSwap (unapproved/disabled/too-large/spending-limit/window-reset), LP policy (disabled/addLiquidity-too-large/removeLiquidity-too-large/feeWithdrawal-limit/window-reset), recorder access, and owner-only config.

- [x] Implement policy state:

```solidity
struct TraderPolicy {
    bool enabled;
    uint256 maxSwapAmount;
    uint256 spendingLimit;
    uint256 spentAmount;
    uint256 windowStart;
    uint256 windowDuration;
}
struct LPPolicy {
    bool enabled;
    uint256 maxLiquidityAdd;
    uint256 maxLiquidityRemove;
    uint256 maxFeeWithdrawal;
    uint256 withdrawnFees;
    uint256 windowStart;
    uint256 windowDuration;
}
mapping(address => bool) public isTokenApproved;
mapping(address => TraderPolicy) public traderPolicies;
mapping(address => LPPolicy) public lpPolicies;
mapping(address => bool) public isRecorder;
```

- [x] Implement owner-only configuration:

```solidity
function setTokenApproval(address token, bool approved) external onlyOwner;
function setTraderPolicy(address trader, bool enabled, uint256 maxSwapAmount, uint256 spendingLimit, uint256 windowDuration) external onlyOwner;
function setLPPolicy(address lp, bool enabled, uint256 maxLiquidityAdd, uint256 maxLiquidityRemove, uint256 maxFeeWithdrawal, uint256 windowDuration) external onlyOwner;
function setRecorder(address recorder, bool approved) external onlyOwner;
```

- [x] Implement validation (view functions that revert on violation):

```solidity
function validateSwap(address trader, address tokenIn, uint256 amountIn) external view;
function validateLiquidityAdd(address lp, uint256 amountA, uint256 amountB) external view;
function validateLiquidityRemove(address lp, uint256 lpShares) external view;
function validateFeeWithdrawal(address lp, uint256 amount) external view;
```

- [x] Implement recorder-only state updates:

```solidity
function recordSpending(address trader, uint256 amount) external; // recorder-only
function recordFeeWithdrawal(address lp, uint256 amount) external; // recorder-only
```

- [x] Rolling-window helpers (reset spent amounts when window has expired):

```solidity
function currentSpentAmount(address trader) public view returns (uint256);
function currentFeeWithdrawn(address lp) public view returns (uint256);
```

- [x] Verify:

```powershell
npm test -- test/AgentPolicy.test.ts
```

### Task 3: Implement `LPToken.sol`

**Responsibility:** ERC-20 LP token minted and burned exclusively by the AMMPool. Deployment order: LPToken → FeeVault → AMMPool → `lpToken.setPool(pool)` → `feeVault.setPool(pool)`.

**Files:**
- Create: `contracts/LPToken.sol`
- Create: `test/LPToken.test.ts`

- [x] Write tests for setPool once-only, zero address rejection, pool mint/burn, non-pool rejection, and mint before pool is set.

- [x] Implement pool-gated mint/burn:

```solidity
contract LPToken is ERC20, Ownable {
    address public pool;

    function setPool(address pool_) external onlyOwner {
        require(pool == address(0), "LPTOKEN_POOL_ALREADY_SET");
        require(pool_ != address(0), "LPTOKEN_ZERO_POOL");
        pool = pool_;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == pool, "LPTOKEN_NOT_POOL");
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external {
        require(msg.sender == pool, "LPTOKEN_NOT_POOL");
        _burn(from, amount);
    }
}
```

- [x] Verify:

```powershell
npm test -- test/LPToken.test.ts
```

---

## Milestone 3: AMM Pool and Fee Vault

### Task 4: Implement `AMMPool.sol`

**Responsibility:** Constant-product AMM (x·y = k). Accepts two ERC-20 tokens, issues LP tokens, charges a swap fee (default 0.30% = 30 bps) forwarded to FeeVault.

**Files:**
- Create: `contracts/AMMPool.sol`
- Create: `test/AMMPool.test.ts`

- [x] Write tests for first-add sqrt LP shares, subsequent proportional LP shares, remove liquidity, swap A→B and B→A formulas, fee forwarding to FeeVault, policy violations, spotPrice, setFeeBps, and events.

- [x] Implement addLiquidity:

```solidity
function addLiquidity(uint256 amountA, uint256 amountB) external returns (uint256 lpShares) {
    // first add: lpShares = sqrt(amountA * amountB)
    // subsequent: lpShares = min(amountA * total / reserveA, amountB * total / reserveB)
}
```

- [x] Implement removeLiquidity:

```solidity
function removeLiquidity(uint256 lpShares) external returns (uint256 amountA, uint256 amountB) {
    // amountA = lpShares * reserveA / totalSupply
    // amountB = lpShares * reserveB / totalSupply
}
```

- [x] Implement swap with fee:

```solidity
function swap(address tokenIn, uint256 amountIn) external returns (uint256 amountOut) {
    // fee = amountIn * feeBps / 10_000
    // amountOut = reserveOut * amountInLessFee / (reserveIn + amountInLessFee)
    // fee tokens transferred to FeeVault; feeVault.notifyFee() called
    // policy.recordSpending() called after successful swap
}
```

- [x] Implement read helpers:

```solidity
function spotPrice() external view returns (uint256); // reserveB * 1e18 / reserveA
function setFeeBps(uint256 newFeeBps) external onlyOwner; // max 1000
```

- [x] Verify:

```powershell
npm test -- test/AMMPool.test.ts
```

### Task 5: Implement `FeeVault.sol`

**Responsibility:** Accumulate swap fees from AMMPool and let LP token holders withdraw their proportional share subject to policy limits.

**Files:**
- Create: `contracts/FeeVault.sol`
- Create: `test/FeeVault.test.ts`

- [x] Write tests for setPool once-only, notifyFee (pool-only, invalid token, event), collectFees (proportional payout, totalFees reduction, zero-shares revert, insufficient-balance revert, zero-fees revert), and constructor zero-address guards.

- [x] Implement fee accumulation:

```solidity
function notifyFee(address token, uint256 amount) external {
    require(msg.sender == pool, "FEEVAULT_NOT_POOL");
    // accumulate totalFeesA or totalFeesB
}
```

- [x] Implement proportional fee collection:

```solidity
function collectFees(uint256 lpShares) external {
    // feesA = totalFeesA * lpShares / lpToken.totalSupply()
    // feesB = totalFeesB * lpShares / lpToken.totalSupply()
    // policy.validateFeeWithdrawal() → transfer → policy.recordFeeWithdrawal()
}
```

- [x] Verify:

```powershell
npm test -- test/FeeVault.test.ts
```

---

## Milestone 4: Deployment and Integration Tests

### Task 6: Add Deployment Reference and ABI Export

**Files:**
- Create: `scripts/deploy.ts` (reference only)
- Create: `scripts/export_abis.ts`
- Modify: `README.md`

- [ ] `scripts/deploy.ts` documents the deployment order: `MockERC20 (×2)` → `AgentPolicy` → `LPToken` → `FeeVault` → `AMMPool` → `lpToken.setPool(pool)` → `feeVault.setPool(pool)`.
- [ ] After deployment, call policy setup from the deployer wallet: `setTokenApproval`, `setTraderPolicy`, `setLPPolicy`, `setRecorder(pool)`, `setRecorder(feeVault)`.
- [ ] `scripts/export_abis.ts` reads Hardhat artifacts and writes `agents/abis/{AgentPolicy,LPToken,AMMPool,FeeVault}.json`.

Deployment is done manually via Remix IDE on Sepolia. After deployment, copy all addresses into `.env`. Run `npm run export:abis` once after compile to generate ABI files for Python agents.

`.env` keys:

```text
SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
DEPLOYER_PRIVATE_KEY=0x...
TRADER_PRIVATE_KEYS=0x...,0x...,0x...,0x...,0x...
TRADER_MODELS=gemini-2.0-flash-lite,llama-3.1-8b-instant,gpt-4o-mini,gemini-2.0-flash-lite,llama-3.3-70b-versatile
LP_PRIVATE_KEYS=0x...,0x...
LP_MODELS=gemini-2.0-flash-lite,gpt-4o-mini
TOKEN_A_ADDRESS=0x...
TOKEN_B_ADDRESS=0x...
LP_TOKEN_ADDRESS=0x...
POLICY_ADDRESS=0x...
POOL_ADDRESS=0x...
VAULT_ADDRESS=0x...
GOOGLE_API_KEY=...
GROQ_API_KEY=...
OPENAI_API_KEY=...
```

### Task 7: Add Full Solidity Integration Test

**Files:**
- Create: `test/IntegrationMarket.test.ts`

- [ ] Deploy all contracts (MockERC20 ×2, AgentPolicy, LPToken, FeeVault, AMMPool).
- [ ] Wire setPool on LPToken and FeeVault.
- [ ] Configure policy: approve tokens, set trader policy, set LP policy, set pool and vault as recorders.
- [ ] Fund LP and traders with tokenA and tokenB.
- [ ] LP adds initial liquidity → verify LP shares minted, reserves updated.
- [ ] Trader swaps A→B → verify amountOut, fee in FeeVault, Swap event.
- [ ] LP collects fees → verify token balances increase, FeesCollected event.
- [ ] LP removes liquidity → verify tokens returned, LiquidityRemoved event.
- [ ] Assert oversized swap reverts with POLICY_SWAP_TOO_LARGE.
- [ ] Assert swap of unapproved token reverts with POLICY_TOKEN_NOT_APPROVED.
- [ ] Assert addLiquidity from disabled LP reverts with POLICY_LP_DISABLED.

Verification:

```powershell
npm test
```

Expected: All contract unit tests and integration test pass.

---

## Milestone 5: Deployed LLM Agent Layer

### Task 8: Implement Portfolio Tracker

**Files:**
- Create: `agents/portfolio.py`
- Create: `test/test_portfolio.py`

**Behavior:**
- Pending trades do not mutate confirmed state.
- Confirmed swap decreases one token balance and increases the other.
- Confirmed liquidity add decreases both token balances and increases LP shares.
- Confirmed liquidity remove increases both token balances and decreases LP shares.
- Reverted or missing transactions discard pending state without mutation.

Core model:

```python
from dataclasses import dataclass, field

@dataclass
class PendingTrade:
    side: str       # "SWAP", "ADD_LIQUIDITY", "REMOVE_LIQUIDITY", "COLLECT_FEES"
    symbol: str
    shares: int
    payment: int

@dataclass
class Portfolio:
    cash: int
    holdings: dict[str, int] = field(default_factory=dict)
    pending: dict[str, PendingTrade] = field(default_factory=dict)
```

- [x] Implement `record_pending`, `confirm`, and `discard` methods.
- [x] `confirm` raises `KeyError` for unknown tx_hash.
- [x] `discard` is a silent no-op for unknown tx_hash.

Verification:

```powershell
pytest test/test_portfolio.py
```

### Task 9: Implement Config, LLM Client, and Decision Schemas

**Files:**
- Create: `agents/config.py`
- Create: `agents/llm.py`
- Create: `agents/schemas.py`
- Create: `test/test_schemas.py`

**Behavior:**
- `config.py` loads Sepolia RPC URL, contract addresses, per-trader and per-LP wallet/model pairs from `.env`. Traders are paired by index from `TRADER_PRIVATE_KEYS` / `TRADER_MODELS`; LPs from `LP_PRIVATE_KEYS` / `LP_MODELS`. Length mismatch raises `RuntimeError`.
- `llm.py` wraps OpenAI, Google Gemini, and Groq; routes each call to the correct provider based on model name prefix; supports mock mode for tests.
- `schemas.py` stores Pydantic decision models and validation helpers.
- Trader decisions: `SWAP` (tokenIn, amountIn), `HOLD`.
- LP decisions: `ADD_LIQUIDITY` (amountA, amountB), `REMOVE_LIQUIDITY` (lpShares), `COLLECT_FEES` (lpShares), `HOLD`.
- Invalid JSON, missing fields, unknown actions, or negative amounts are rejected before transaction submission.
- Unit tests use mock LLM responses and never call paid APIs.

Core config models:

```python
@dataclass(frozen=True)
class TraderConfig:
    private_key: str
    model: str

@dataclass(frozen=True)
class LPConfig:
    private_key: str
    model: str

@dataclass(frozen=True)
class Config:
    rpc_url: str
    token_a: str
    token_b: str
    lp_token: str
    policy: str
    pool: str
    vault: str
    traders: list[TraderConfig]
    lps: list[LPConfig]
    google_api_key: str | None
    groq_api_key: str | None
    openai_api_key: str | None
```

Core decision models:

```python
class TraderDecision(BaseModel):
    action: Literal["SWAP", "HOLD"]
    token_in: str | None = None     # token address
    amount_in: int = Field(default=0, ge=0)
    reason: str

class LPDecision(BaseModel):
    action: Literal["ADD_LIQUIDITY", "REMOVE_LIQUIDITY", "COLLECT_FEES", "HOLD"]
    amount_a: int = Field(default=0, ge=0)
    amount_b: int = Field(default=0, ge=0)
    lp_shares: int = Field(default=0, ge=0)
    reason: str
```

Verification:

```powershell
pytest test/test_schemas.py
```

### Task 10: Implement Chain Access, Local Validation, and Receipt Verification

**Files:**
- Create: `agents/chain.py`
- Create: `test/test_chain_receipts.py`

**Behavior:**
- `chain.py` centralizes Web3 setup, contract loading from ABI files, wallet signing, transaction submission, event lookup, and receipt verification.
- Provides read helpers: token balances, LP token balance, reserves (`reserveA`, `reserveB`), spot price, policy limits, accumulated fees.
- Local validation rejects obviously non-compliant LLM decisions before sending transactions. Smart contracts remain the final authority.
- Receipt outcomes: `CONFIRMED` (success + expected event found), `REJECTED` (revert or expected event missing), `PENDING` (timeout or no receipt).

Core result type:

```python
@dataclass(frozen=True)
class ExecutionResult:
    tx_hash: str
    status: str           # "CONFIRMED" | "REJECTED" | "PENDING"
    block_number: int | None
    event_found: bool
```

Verification:

```powershell
pytest test/test_chain_receipts.py
```

### Task 11: Implement LP and Trader Agents

**Files:**
- Create: `agents/lp_agent.py`
- Create: `agents/trader_agent.py`
- Create: `test/test_agents_with_mock_llm.py`

LP agent methods:

```text
observe() -> dict     # reserves, spot price, own LP balance, own token balances, vault fees
decide(obs: dict) -> LPDecision
execute(decision: LPDecision) -> str | None   # returns tx_hash or None for HOLD
verify(tx_hash: str, expected_event: str) -> ExecutionResult
```

Trader agent methods:

```text
observe() -> dict     # spot price, own token balances, policy remaining
decide(obs: dict) -> TraderDecision
execute(decision: TraderDecision) -> str | None
verify(tx_hash: str, expected_event: str) -> ExecutionResult
```

Services:

```text
python -m agents.lp_agent --index 0 --once
python -m agents.lp_agent --index 1 --interval 30
python -m agents.trader_agent --index 0 --once
python -m agents.trader_agent --index 1 --interval 15
```

`--index` selects the agent by position in `config.lps` or `config.traders`. Each process uses the wallet and LLM model at that index.

Verification:

```powershell
pytest test/test_agents_with_mock_llm.py
python -m compileall agents
```

Expected: All agent modules compile.

---

## Milestone 6: End-to-End Demo

### Task 12: Implement Demo Runner and Checklist

**Files:**
- Create: `agents/run_demo.py`
- Create: `docs/demo-checklist.md`
- Modify: `README.md`

Demo sequence:

```text
1. Load Sepolia contract addresses and per-agent wallet/model pairs from .env.
2. Start one LP agent and two trader agents (each with its own wallet and LLM model).
3. LP 0 (e.g. Gemini Flash) adds initial liquidity → LiquidityAdded event logged.
4. Trader 0 (e.g. Gemini Flash) observes spot price and swaps tokenA → tokenB → Swap event logged.
5. Trader 1 (e.g. Llama via Groq) observes spot price and swaps tokenB → tokenA → Swap event logged.
6. LP 0 collects accumulated swap fees → FeesCollected event logged.
7. LP 0 removes half its liquidity → LiquidityRemoved event logged.
8. Oversized swap is proposed by an LLM decision and rejected on-chain (POLICY_SWAP_TOO_LARGE).
9. Swap of unapproved token is proposed and rejected on-chain (POLICY_TOKEN_NOT_APPROVED).
10. addLiquidity from a disabled LP is rejected on-chain (POLICY_LP_DISABLED).
11. Final portfolio state is printed with no changes from rejected transactions.
```

`docs/demo-checklist.md`:

```markdown
# Demo Checklist

- [ ] `npm test` passes (all Solidity unit + integration tests).
- [ ] `pytest test` passes (all Python unit tests).
- [ ] `python -m compileall agents` passes.
- [ ] Contracts deployed on Sepolia via Remix IDE in order:
      MockERC20 (×2) → AgentPolicy → LPToken → FeeVault → AMMPool
      → lpToken.setPool(pool) → feeVault.setPool(pool)
- [ ] Policy configured: tokens approved, trader/LP policies set, pool+vault set as recorders.
- [ ] All addresses recorded in `.env`.
- [ ] `npm run export:abis` generates `agents/abis/*.json`.
- [ ] LLM provider API keys and per-agent model assignments read from `.env`.
- [ ] LP and trader agents run as separate wallet-backed processes.
- [ ] Logs show: observation summary, LLM decision, tx hash, receipt status, verified event.
- [ ] Successful swap shows `Swap` event and portfolio token balances update.
- [ ] Fee collection shows `FeesCollected` event and portfolio balances update.
- [ ] Liquidity add/remove shows `LiquidityAdded`/`LiquidityRemoved` and LP shares update.
- [ ] Oversized swap reverts and portfolio is unchanged.
- [ ] Unapproved token swap reverts and portfolio is unchanged.
- [ ] Disabled LP addLiquidity reverts and portfolio is unchanged.
- [ ] README explains how to reproduce the demo.
```

Final verification:

```powershell
npm test
pytest test
python -m compileall agents
```

---

## Evaluation Criteria

The project is complete when:

- Smart contracts enforce approved tokens, maximum swap sizes, per-trader spending limits, per-LP liquidity and fee-withdrawal limits, and atomic settlement.
- Swap output follows the constant-product formula (x·y = k) with configurable fee.
- Swap fees accumulate in FeeVault and are claimable proportionally by LP token holders.
- LP token minting/burning is controlled exclusively by AMMPool.
- Python agents submit transactions but do not directly mutate authoritative market state.
- LP and trader agents run as independently deployable LLM-backed services with distinct wallets.
- LLM decisions are structured, schema-validated, and treated as intent rather than permission.
- Local portfolio state updates only after confirmed receipts and expected events.
- Reverted transactions leave local portfolio state unchanged.
- Tests use mock LLM clients and do not require paid API calls.
- The demo is reproducible from README instructions.

## Implementation Notes

- Keep economic authority in Solidity. Off-chain checks are advisory only.
- LLM intent is never compliance. Smart contracts must remain the final authority.
- Keep prompts short, use structured JSON outputs, cap output tokens, and prefer low-cost models.
- Never run paid LLM calls in unit tests; inject mock LLM clients.
- Contracts are deployed manually via Remix IDE on Sepolia. `scripts/deploy.ts` is reference only.
- Fee collection in FeeVault tracks cumulative fees and per-LP claimed amounts so the same LP shares cannot claim the same fees twice.
- First LP add uses Babylonian sqrt(amountA × amountB) to avoid ratio-dependent initialization.
- Emit events for every important state transition so agents can verify outcomes.
- Prefer small contracts and direct tests over broad abstractions.
