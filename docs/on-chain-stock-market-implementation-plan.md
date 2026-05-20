# On-Chain Stock Market Simulation Implementation Plan

**Goal:** Build a reproducible prototype where deployed LLM-based trading and firm agents interact with Solidity smart contracts that enforce stock ownership, approved assets, trade limits, issuance caps, dividends, and receipt-verified local portfolio updates.

**Architecture:** The blockchain is the source of truth for balances, share ownership, approved assets, spending limits, and settlement results. Each LLM agent runs as an off-chain service with its own wallet, observes chain state through RPC, asks a low-cost LLM API for a structured decision, validates that decision locally, submits transactions through Web3, and updates local state only after confirmed receipts and expected events.

**Tech Stack:** Solidity, Hardhat, TypeScript tests, Hardhat test network, Python 3.12, Web3.py, pytest, Pydantic, python-dotenv, multiple LLM providers (OpenAI, Google Gemini, Groq) with per-trader model assignment. Contracts deployed on Sepolia testnet via Remix IDE.

---

## Requirements From `DesignDocument.pdf`

- Firm agents represent listed companies. They run as LLM-backed services that can issue shares, publish simulated announcements, and trigger dividend payments from a firm wallet.
- Trader agents represent investors. They run as LLM-backed services that monitor prices, announcements, transaction history, policy state, and their own portfolios from trader wallets.
- Smart contracts enforce share supply caps, approved assets, spending limits, maximum trade size, dividend budgets, and atomic settlement.
- RPC and wallet infrastructure prepares, signs, submits, and confirms transactions.
- LLM outputs are advisory intent only. They must be parsed as structured decisions, validated by local code, and enforced by smart contracts.
- Agents must be deployable as separate long-running processes, not only one-shot demo functions.
- Local portfolio state is not authoritative and must update only after confirmed on-chain execution.
- Reverted transactions must not corrupt local portfolio state.
- The demo must show successful buy, successful sell, dividend distribution, oversized trade rejection, unauthorized asset rejection, excessive mint rejection, excessive dividend rejection, and recovery from a revert.

## Repository Layout

```text
contracts/
  AgentPolicy.sol
  StockToken.sol
  Exchange.sol
  DividendVault.sol
  test/
    MockERC20.sol
scripts/
  deploy.ts          (reference only — deploy via Remix IDE)
  export_abis.ts
test/
  AgentPolicy.test.ts
  StockToken.test.ts
  Exchange.test.ts
  DividendVault.test.ts
  IntegrationMarket.test.ts
agents/
  __init__.py
  config.py
  llm.py
  schemas.py
  chain.py
  portfolio.py
  firm_agent.py
  trader_agent.py
  run_demo.py
  abis/
    AgentPolicy.json
    StockToken.json
    Exchange.json
    DividendVault.json
tests/
  test_portfolio.py
  test_schemas.py
  test_chain_receipts.py
  test_agents_with_mock_llm.py
docs/
  on-chain-stock-market-implementation-plan.md
  llm-agent-deployment.md
  demo-checklist.md
hardhat.config.ts
package.json
requirements.txt
README.md
```

---

## Milestone 1: Project Scaffolding

### Task 1: Initialize Hardhat and Python Tooling

**Files:**
- Create: `package.json`
- Create: `hardhat.config.ts`
- Create: `requirements.txt`
- Modify: `README.md`

- [ ] Create `package.json` with scripts:

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

- [ ] Create `hardhat.config.ts`:

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

- [ ] Create `requirements.txt`:

```text
web3==6.20.1
pytest==8.2.2
python-dotenv==1.0.1
pydantic==2.8.2
openai==1.40.0
google-generativeai==0.8.3
groq==0.11.0
```

- [ ] Install dependencies:

```powershell
npm install
python -m pip install -r requirements.txt
```

- [ ] Verify scaffolding:

```powershell
npm run compile
```

Expected: Hardhat compiles successfully or reports nothing to compile.

---

## Milestone 2: Core Smart Contracts

### Task 2: Implement `AgentPolicy.sol`

**Responsibility:** Store enforceable autonomous-agent constraints: approved tokens, maximum trade sizes, spending limits, spending usage, dividend budgets, and authorized spending recorders.

**Files:**
- Create: `contracts/AgentPolicy.sol`
- Create: `test/AgentPolicy.test.ts`

- [ ] Write tests for approved-token storage, trader limit storage, dividend budget storage, unauthorized owner calls, and unauthorized spending recorder calls.

- [ ] Implement policy state and events:

```solidity
mapping(address => bool) public isTokenApproved;
mapping(address => uint256) public maxTradeSize;
mapping(address => uint256) public spendingLimit;
mapping(address => uint256) public spentAmount;
mapping(address => uint256) public dividendBudget;
mapping(address => bool) public isSpendingRecorder;
```

- [ ] Implement owner-only configuration:

```solidity
function setTokenApproved(address token, bool approved) external onlyOwner;
function setTraderLimits(address trader, uint256 maxTradeSize, uint256 spendingLimit) external onlyOwner;
function setDividendBudget(address firm, uint256 budget) external onlyOwner;
function setSpendingRecorder(address recorder, bool approved) external onlyOwner;
```

- [ ] Implement trade validation:

```solidity
function validateTrade(address trader, address token, uint256 shareAmount, uint256 paymentAmount) external view {
    require(isTokenApproved[token], "POLICY_TOKEN_NOT_APPROVED");
    require(shareAmount <= maxTradeSize[trader], "POLICY_TRADE_TOO_LARGE");
    require(spentAmount[trader] + paymentAmount <= spendingLimit[trader], "POLICY_SPENDING_LIMIT");
}
```

- [ ] Implement spending recording:

```solidity
function recordSpending(address trader, uint256 amount) external {
    require(isSpendingRecorder[msg.sender], "POLICY_NOT_SPENDING_RECORDER");
    spentAmount[trader] += amount;
}
```

- [ ] Verify:

```powershell
npm test -- test/AgentPolicy.test.ts
```

### Task 3: Implement `StockToken.sol`

**Responsibility:** ERC-20-style token representing firm shares with firm-only minting and a hard maximum supply cap.

**Files:**
- Create: `contracts/StockToken.sol`
- Create: `test/StockToken.test.ts`

- [ ] Write tests for authorized minting, unauthorized minting rejection, and cap-exceeded rejection.

- [ ] Implement constructor:

```solidity
constructor(string memory name_, string memory symbol_, address firm_, uint256 maxSupply_) ERC20(name_, symbol_)
```

- [ ] Implement minting rule:

```solidity
function mint(address to, uint256 amount) external {
    require(msg.sender == firm, "TOKEN_NOT_FIRM");
    require(totalSupply() + amount <= maxSupply, "TOKEN_CAP_EXCEEDED");
    _mint(to, amount);
}
```

- [ ] Verify:

```powershell
npm test -- test/StockToken.test.ts
```

---

## Milestone 3: Exchange and Dividend Logic

### Task 4: Implement `Exchange.sol`

**Responsibility:** Settle buy and sell orders atomically while checking policy constraints.

**Files:**
- Create: `contracts/Exchange.sol`
- Create: `test/Exchange.test.ts`

- [ ] Write tests for successful buy settlement.
- [ ] Write tests for successful sell settlement.
- [ ] Write tests that oversized trades revert.
- [ ] Write tests that unauthorized token trades revert.
- [ ] Write tests that spending-limit violations revert.
- [ ] Write tests that `TradeSettled` is emitted for successful trades.

- [ ] Implement buy flow:

```solidity
function buy(address stockToken, address seller, uint256 shareAmount, uint256 paymentAmount) external {
    policy.validateTrade(msg.sender, stockToken, shareAmount, paymentAmount);
    require(paymentToken.transferFrom(msg.sender, seller, paymentAmount), "EXCHANGE_PAYMENT_FAILED");
    require(IERC20(stockToken).transferFrom(seller, msg.sender, shareAmount), "EXCHANGE_SHARE_FAILED");
    policy.recordSpending(msg.sender, paymentAmount);
    emit TradeSettled(msg.sender, stockToken, seller, shareAmount, paymentAmount, true);
}
```

- [ ] Implement sell flow:

```solidity
function sell(address stockToken, address buyer, uint256 shareAmount, uint256 paymentAmount) external {
    policy.validateTrade(msg.sender, stockToken, shareAmount, 0);
    require(IERC20(stockToken).transferFrom(msg.sender, buyer, shareAmount), "EXCHANGE_SHARE_FAILED");
    require(paymentToken.transferFrom(buyer, msg.sender, paymentAmount), "EXCHANGE_PAYMENT_FAILED");
    emit TradeSettled(msg.sender, stockToken, buyer, shareAmount, paymentAmount, false);
}
```

- [ ] Verify:

```powershell
npm test -- test/Exchange.test.ts
```

### Task 5: Implement `DividendVault.sol`

**Responsibility:** Hold firm reserves and distribute dividends subject to firm dividend budgets.

**Files:**
- Create: `contracts/DividendVault.sol`
- Create: `test/DividendVault.test.ts`

- [ ] Write tests for reserve deposit.
- [ ] Write tests for successful dividend distribution.
- [ ] Write tests for `DividendPaid` events.
- [ ] Write tests for payout above budget rejection.
- [ ] Write tests for payout above reserve rejection.
- [ ] Write tests for holder/amount length mismatch rejection.

- [ ] Implement deposit:

```solidity
function deposit(uint256 amount) external {
    require(paymentToken.transferFrom(msg.sender, address(this), amount), "DIVIDEND_DEPOSIT_FAILED");
    firmReserve[msg.sender] += amount;
    emit DividendDeposited(msg.sender, amount);
}
```

- [ ] Implement distribution:

```solidity
function distribute(address stockToken, address[] calldata holders, uint256[] calldata amounts) external {
    require(holders.length == amounts.length, "DIVIDEND_LENGTH_MISMATCH");
    uint256 total;
    for (uint256 i = 0; i < amounts.length; i++) {
        total += amounts[i];
    }
    require(total <= policy.dividendBudget(msg.sender), "DIVIDEND_BUDGET_EXCEEDED");
    require(total <= firmReserve[msg.sender], "DIVIDEND_RESERVE_EXCEEDED");
    firmReserve[msg.sender] -= total;
    for (uint256 i = 0; i < holders.length; i++) {
        require(paymentToken.transfer(holders[i], amounts[i]), "DIVIDEND_PAYMENT_FAILED");
        emit DividendPaid(msg.sender, stockToken, holders[i], amounts[i]);
    }
}
```

- [ ] Verify:

```powershell
npm test -- test/DividendVault.test.ts
```

---

## Milestone 4: Deployment and Integration Tests

### Task 6: Add Local Deployment Script

**Files:**
- Create: `scripts/deploy.ts` (reference only)
- Create: `scripts/export_abis.ts`
- Modify: `README.md`

- [ ] Deploy payment token, stock token, policy, exchange, and dividend vault.
- [ ] Configure approved stock token.
- [ ] Configure trader max trade size and spending limit.
- [ ] Configure firm dividend budget.
- [ ] Authorize the exchange and dividend vault as spending recorders.
- [ ] Print deployed addresses as JSON so Python agents can consume them.
- [ ] Implement `scripts/export_abis.ts` to extract ABIs from Hardhat artifacts into `agents/abis/*.json`.

Verification:

Contracts are deployed manually via Remix IDE on Sepolia testnet in this order: `MockERC20` → `AgentPolicy` → `StockToken` → `Exchange` → `DividendVault`. After deployment, call the policy setup functions (`setTokenPolicy`, `setTraderPolicy`, `setDividendPolicy`, `setRecorder`) from the firm wallet. Copy all deployed addresses into `.env` (use `.env.example` as the template). Run `npm run export:abis` once after compile to generate `agents/abis/*.json` for Python agents to load. `scripts/deploy.ts` is kept as reference only.

### Task 7: Add Full Solidity Integration Test

**Files:**
- Create: `test/IntegrationMarket.test.ts`

- [ ] Deploy all contracts.
- [ ] Mint payment tokens and shares to test actors.
- [ ] Approve exchange and dividend vault transfers.
- [ ] Execute successful buy.
- [ ] Execute successful sell.
- [ ] Execute successful dividend distribution.
- [ ] Assert oversized trade reverts.
- [ ] Assert unauthorized asset trade reverts.
- [ ] Assert excessive share mint reverts.
- [ ] Assert excessive dividend payout reverts.

Verification:

```powershell
npm test
```

Expected: All contract unit tests and integration tests pass.

---

## Milestone 5: Deployed LLM Agent Layer

### Task 8: Implement Portfolio Tracker

**Files:**
- Create: `agents/portfolio.py`
- Create: `tests/test_portfolio.py`

**Behavior:**
- Pending trades do not mutate confirmed state.
- Confirmed buy decreases cash and increases holdings.
- Confirmed sell increases cash and decreases holdings.
- Reverted or missing transactions discard pending state.

Core model:

```python
from dataclasses import dataclass, field

@dataclass
class PendingTrade:
    side: str
    symbol: str
    shares: int
    payment: int

@dataclass
class Portfolio:
    cash: int
    holdings: dict[str, int] = field(default_factory=dict)
    pending: dict[str, PendingTrade] = field(default_factory=dict)
```

Verification:

```powershell
pytest tests/test_portfolio.py
```

### Task 9: Implement Config, LLM Client, and Decision Schemas

**Files:**
- Create: `agents/config.py`
- Create: `agents/llm.py`
- Create: `agents/schemas.py`
- Create: `tests/test_schemas.py`

**Behavior:**
- `config.py` loads Sepolia RPC URL, contract addresses, wallet keys, and per-trader LLM model assignments from `.env`. Each trader has its own private key and LLM model, paired by index via `TRADER_PRIVATE_KEYS` and `TRADER_MODELS` (comma-separated, same length). Three provider API keys are loaded optionally: `GOOGLE_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`.
- `llm.py` wraps multiple LLM providers (OpenAI, Google Gemini, Groq) and routes each call to the correct provider based on the trader's assigned model name. Supports a mock mode for tests and offline demos.
- `schemas.py` stores the Pydantic decision models and simple validation helpers.
- Prompts can live in `llm.py` as small constants or helper functions; a separate prompt module is unnecessary for this prototype.
- Agent prompts must request compact structured JSON decisions only.
- Trader decisions support `BUY`, `SELL`, and `HOLD`.
- Firm decisions support `ANNOUNCE`, `ISSUE_SHARES`, `DEPOSIT_DIVIDEND_RESERVE`, `PAY_DIVIDEND`, and `HOLD`.
- Invalid JSON, missing fields, unknown actions, negative amounts, or invented symbols are rejected before transaction submission.
- Unit tests use mock LLM responses and never call paid APIs.

`.env` keys for this task:

```text
SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
FIRM_PRIVATE_KEY=0x...
TRADER_PRIVATE_KEYS=0x...,0x...,0x...,0x...,0x...
TRADER_MODELS=gemini-2.0-flash-lite,llama-3.1-8b-instant,gpt-4o-mini,gemini-2.0-flash-lite,llama-3.3-70b-versatile
PAYMENT_TOKEN_ADDRESS=0x...
STOCK_TOKEN_ADDRESS=0x...
POLICY_ADDRESS=0x...
EXCHANGE_ADDRESS=0x...
VAULT_ADDRESS=0x...
GOOGLE_API_KEY=...
GROQ_API_KEY=...
OPENAI_API_KEY=...
```

Core config models:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TraderConfig:
    private_key: str
    model: str          # e.g. "gemini-2.0-flash-lite", "llama-3.1-8b-instant", "gpt-4o-mini"

@dataclass(frozen=True)
class Config:
    rpc_url: str
    payment_token: str
    stock_token: str
    policy: str
    exchange: str
    vault: str
    firm_private_key: str
    traders: list[TraderConfig]   # paired by index from TRADER_PRIVATE_KEYS / TRADER_MODELS
    google_api_key: str | None
    groq_api_key: str | None
    openai_api_key: str | None
```

Core decision models:

```python
from typing import Literal
from pydantic import BaseModel, Field

class TraderDecision(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    symbol: str | None = None
    shares: int = Field(default=0, ge=0)
    max_payment: int = Field(default=0, ge=0)
    reason: str

class FirmDecision(BaseModel):
    action: Literal["ANNOUNCE", "ISSUE_SHARES", "DEPOSIT_DIVIDEND_RESERVE", "PAY_DIVIDEND", "HOLD"]
    message: str | None = None
    target_holder: str | None = None
    amount: int = Field(default=0, ge=0)
    reason: str
```

Verification:

```powershell
pytest tests/test_schemas.py
```

### Task 10: Implement Chain Access, Local Validation, and Receipt Verification

**Files:**
- Create: `agents/chain.py`
- Create: `tests/test_chain_receipts.py`

**Behavior:**
- `chain.py` centralizes Web3 setup, contract loading, wallet signing, transaction submission, event lookup, and receipt verification.
- `chain.py` provides small helper methods for reading balances, holdings, approved assets, max trade size, spending remaining, dividend budgets, recent prices, and recent events.
- Local validation can live in `chain.py` or inside the agent class methods. It rejects malformed or obviously non-compliant LLM decisions before sending transactions.
- Local validation is not the final authority; smart contracts remain the compliance layer.
- Successful receipt with expected event returns `CONFIRMED`.
- Reverted receipt returns `REJECTED`.
- Successful receipt missing expected event returns `REJECTED`.
- Timeout or missing receipt returns `PENDING`.

Core result type:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ExecutionResult:
    tx_hash: str
    status: str
    block_number: int | None
    event_found: bool
```

Verification:

```powershell
pytest tests/test_chain_receipts.py
```

### Task 11: Implement Deployed Firm and Trader Agents

**Files:**
- Create: `agents/firm_agent.py`
- Create: `agents/trader_agent.py`
- Create: `tests/test_agents_with_mock_llm.py`

Firm agent methods:

```text
observe() -> dict
decide(observation: dict) -> FirmDecision
execute(decision: FirmDecision) -> str | None
verify(tx_hash: str, expected_event_name: str) -> ExecutionResult
```

Trader agent methods:

```text
observe() -> dict
decide(observation: dict) -> TraderDecision
execute(decision: TraderDecision) -> str | None
verify(tx_hash: str, expected_event_name: str) -> ExecutionResult
```

Services:

```text
python -m agents.firm_agent --once
python -m agents.trader_agent --index 0 --once
python -m agents.trader_agent --index 1 --interval 15
```

`--index` selects the trader by position in `config.traders` (paired from `TRADER_PRIVATE_KEYS` / `TRADER_MODELS`). Each process uses the wallet and LLM model at that index.

Verification:

```powershell
pytest tests/test_agents_with_mock_llm.py
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
1. Load Sepolia contract addresses and per-trader wallet/model pairs from .env.
2. Start firm agent and two trader agents (each with its own wallet and LLM model).
3. Firm LLM agent observes market state and issues shares to the market maker.
4. Firm LLM agent publishes a simulated announcement.
5. Trader 0 (e.g. Gemini Flash) observes chain state and decides a successful buy.
6. Trader 1 (e.g. Llama via Groq) observes chain state and decides a successful sell.
7. Firm LLM agent deposits reserve and pays dividend.
8. Oversized trade is proposed by an LLM decision and rejected locally or on-chain.
9. Unauthorized asset trade is proposed by an LLM decision and rejected locally or on-chain.
10. Excessive mint is attempted and rejected.
11. Excessive dividend payout is attempted and rejected.
12. Final portfolio state is printed with no changes from rejected transactions.
```

`docs/demo-checklist.md`:

```markdown
# Demo Checklist

- [ ] `npm test` passes.
- [ ] `pytest tests` passes.
- [ ] `python -m compileall agents` passes.
- [ ] Contracts deployed on Sepolia via Remix IDE and addresses recorded in `.env`.
- [ ] `npm run export:abis` generates `agents/abis/*.json` from compiled artifacts.
- [ ] LLM provider API keys (`GOOGLE_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`) and per-trader models (`TRADER_MODELS`) are read from `.env`.
- [ ] Firm and trader agents run as separate wallet-backed services.
- [ ] Agent logs show observation summary, LLM decision, transaction hash, receipt status, and verified event.
- [ ] Successful buy shows `TradeSettled` and portfolio cash decreases.
- [ ] Successful sell shows `TradeSettled` and portfolio cash increases.
- [ ] Dividend distribution shows `DividendPaid`.
- [ ] Oversized trade reverts and portfolio is unchanged.
- [ ] Unauthorized asset trade reverts and portfolio is unchanged.
- [ ] Excessive mint reverts.
- [ ] Excessive dividend payout reverts.
- [ ] README explains how to reproduce the demo.
```

Final verification:

```powershell
npm test
pytest tests
python -m compileall agents
```

---

## Evaluation Criteria

The project is complete when:

- Smart contracts enforce approved assets, maximum trade size, spending limits, issuance caps, and dividend budgets.
- Buy and sell settlement is atomic.
- Share issuance above cap reverts.
- Dividend payout above reserve or budget reverts.
- Python agents submit transactions but do not directly mutate authoritative market state.
- Firm and trader agents run as independently deployable LLM-backed services with distinct wallets.
- LLM decisions are structured, schema-validated, and treated as intent rather than permission.
- Local portfolio state updates only after confirmed receipts and expected events.
- Reverted transactions leave local portfolio state unchanged.
- Tests use mock LLM clients and do not require paid API calls.
- The demo is reproducible from README instructions.

## Implementation Notes

- Keep economic authority in Solidity. Off-chain checks are advisory only.
- LLM intent is never compliance. Smart contracts must remain the final authority.
- Keep prompts short, use structured JSON outputs, cap output tokens, and prefer low-cost models for routine agent decisions.
- Never run paid LLM calls in unit tests; inject mock LLM clients.
- Contracts are deployed manually via Remix IDE on Sepolia testnet. Do not use scripts/deploy.ts for deployment. After deployment, contract addresses are provided manually and loaded from .env.
- Keep trading behavior simple. The project is about deployed LLM agents, enforceable payment rules, and auditability, not financial realism.
- Emit events for every important state transition so agents can verify outcomes.
- Prefer small contracts and direct tests over broad abstractions.
