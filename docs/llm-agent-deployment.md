# LLM Agent Deployment Design

## Purpose

This project deploys autonomous LLM-based agents as off-chain services that participate in a blockchain stock market. Agents can decide what they want to do, but they cannot bypass ecosystem rules. Smart contracts are the compliance layer and the final authority for every market action.

The core claim is:

> LLM agents submit market intent through wallet-signed transactions, while Solidity contracts enforce approved assets, trade limits, spending limits, issuance caps, dividend budgets, and atomic settlement.

## Deployment Topology

```text
Local Hardhat Node
  - PaymentToken
  - AgentPolicy
  - StockToken
  - Exchange
  - DividendVault

Firm Agent Service
  - firm wallet private key
  - LLM decision loop
  - Web3 RPC client
  - local memory and logs

Trader Agent Service A
  - trader A wallet private key
  - LLM decision loop
  - Web3 RPC client
  - local portfolio tracker

Trader Agent Service B
  - trader B wallet private key
  - LLM decision loop
  - Web3 RPC client
  - local portfolio tracker
```

Each agent module can run as a real process. For the testnet demo, all processes connect to a Sepolia RPC endpoint and use funded testnet wallets. Contracts can be deployed from Remix IDE, then the resulting addresses are copied into `.env`.

The Python layer should stay intentionally small:

```text
agents/
  config.py        # .env, contract addresses, wallets, model settings
  llm.py           # live LLM provider wrapper and mock LLM mode
  schemas.py       # Pydantic decision and receipt models
  chain.py         # Web3, contracts, transaction submission, receipt checks
  portfolio.py     # confirmed and pending local portfolio state
  trader_agent.py  # trader loop and CLI entry point
  firm_agent.py    # firm loop and CLI entry point
  run_demo.py      # deterministic demo orchestration
```

Do not split prompts, validators, wallets, memory, and service wrappers into separate files unless the implementation becomes too large to understand.

## Compliance Model

The system has three decision layers:

```text
LLM decision: proposes intent
Python validator: rejects malformed or obviously invalid intent
Smart contracts: enforce final compliance
```

The LLM is not trusted with authority. It may recommend a buy, sell, mint, or dividend action, but every action must pass contract checks.

Examples:

- If a trader LLM proposes an unapproved stock token, `AgentPolicy` rejects it.
- If a trader LLM proposes too many shares, `AgentPolicy` rejects it.
- If a trader LLM exceeds its spending limit, `AgentPolicy` rejects it.
- If a firm LLM mints above the share cap, `StockToken` rejects it.
- If a firm LLM pays more dividends than allowed, `DividendVault` rejects it.
- If any asset transfer fails, `Exchange` reverts the whole trade atomically.

Local portfolios update only after receipt confirmation and expected event verification.

## Runtime Configuration

Use `.env` for local deployment configuration:

```text
SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
CHAIN_ID=31337

LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_MAX_OUTPUT_TOKENS=250
LLM_TEMPERATURE=0.2
OPENAI_API_KEY=replace-with-local-demo-key

POLICY_ADDRESS=0x...
EXCHANGE_ADDRESS=0x...
DIVIDEND_VAULT_ADDRESS=0x...
PAYMENT_TOKEN_ADDRESS=0x...
STOCK_TOKEN_ADDRESS=0x...

FIRM_AGENT_ID=firm-a
FIRM_PRIVATE_KEY=0x...

TRADER_A_AGENT_ID=trader-a
TRADER_A_PRIVATE_KEY=0x...

TRADER_B_AGENT_ID=trader-b
TRADER_B_PRIVATE_KEY=0x...
```

Do not commit real API keys or private keys. For the Hardhat demo, use local deterministic accounts only.

## Agent Service Loop

Each deployed service follows the same loop:

```text
1. Load environment and contract addresses.
2. Load the agent wallet.
3. Read chain state through Web3.
4. Build a compact observation.
5. Call the configured low-cost LLM API.
6. Parse structured JSON into a Pydantic decision model.
7. Run local validation.
8. Submit a wallet-signed transaction when needed.
9. Wait for transaction receipt.
10. Verify the expected contract event.
11. Update local memory or portfolio only after confirmation.
12. Log decision, transaction hash, receipt status, and event result.
```

Services should support both one-shot and continuous modes:

```powershell
python -m agents.firm_agent --agent firm-a --once
python -m agents.trader_agent --agent trader-a --once
python -m agents.trader_agent --agent trader-b --interval 15
```

`--once` is useful for deterministic demos. `--interval` is useful for showing long-running deployed behavior.

## Trader Agent

The trader agent observes:

- wallet payment-token balance
- stock-token balance
- local confirmed portfolio
- approved asset status
- maximum trade size
- spending limit and spending used
- recent `TradeSettled` events
- latest firm announcement
- simple price or quote data from the simulation

The trader LLM must return one structured decision:

```json
{
  "action": "BUY",
  "symbol": "ACME",
  "shares": 5,
  "max_payment": 120,
  "reason": "Positive firm announcement and available spending limit."
}
```

Allowed trader actions:

- `BUY`
- `SELL`
- `HOLD`

The trader service maps valid `BUY` and `SELL` decisions to `Exchange.buy(...)` or `Exchange.sell(...)`. The service never directly edits confirmed holdings after sending a transaction. It waits for `TradeSettled`.

## Firm Agent

The firm agent observes:

- firm wallet payment-token balance
- current stock supply
- maximum stock supply
- dividend reserve
- dividend budget
- recent holder list from the demo configuration
- recent trades and market activity

The firm LLM must return one structured decision:

```json
{
  "action": "PAY_DIVIDEND",
  "amount": 100,
  "reason": "Reserve and dividend budget are available."
}
```

Allowed firm actions:

- `ANNOUNCE`
- `ISSUE_SHARES`
- `DEPOSIT_DIVIDEND_RESERVE`
- `PAY_DIVIDEND`
- `HOLD`

`ANNOUNCE` can be stored locally in the demo event log unless an announcement contract is added later. Share issuance, reserve deposits, and dividend payments must go through deployed contracts.

## LLM Provider Strategy

The default demo provider should be low-cost and configurable:

```text
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
```

Provider requirements:

- supports short prompts
- supports JSON or structured output behavior
- has predictable pricing for classroom demos
- can be replaced by a mock client in tests

Cost controls:

- one LLM call per agent per tick
- compact observations only
- no raw full event logs in prompts
- low output token limit
- low temperature
- no paid API calls in tests
- optional `--mock-llm` mode for offline demos

## Prompt Contract

Prompts should be strict and short:

```text
You are an autonomous trader agent in a blockchain stock market simulation.
You must obey the policy values in the observation.
Return only JSON matching the provided schema.
Do not invent assets, balances, permissions, or contract addresses.
If the policy does not allow a safe action, choose HOLD.
```

The prompt should include the observation and the allowed schema. The response should be parsed by code, not trusted as free-form text.

## Failure Handling

The service must handle these cases:

- LLM API timeout: log the failure and choose `HOLD`.
- Invalid JSON: reject the decision and choose `HOLD`.
- Schema validation failure: reject the decision and choose `HOLD`.
- Local validation failure: do not submit a transaction.
- Transaction revert: mark as `REJECTED`.
- Missing expected event: mark as `REJECTED`.
- Receipt timeout: mark as `PENDING` and do not mutate confirmed state.

Rejected and pending transactions must not change confirmed local portfolio state.

## Demo Deployment Sequence

```text
1. Start Hardhat node.
2. Deploy contracts.
3. Configure policy:
   - approve stock token
   - set trader max trade sizes
   - set trader spending limits
   - set firm dividend budget
   - authorize exchange as spending recorder
4. Write deployed addresses and actor wallets to local config.
5. Start firm agent service.
6. Start trader agent services.
7. Run one-shot ticks for deterministic demo actions.
8. Show logs for LLM decisions, transactions, receipts, and verified events.
9. Trigger invalid LLM decisions through mock mode or constrained prompts.
10. Show contract reverts or local rejection and unchanged portfolio state.
```

Recommended local commands:

```powershell
npm run node
npm run deploy:sepolia
python -m agents.firm_agent --agent firm-a --once
python -m agents.trader_agent --agent trader-a --once
python -m agents.trader_agent --agent trader-b --once
python -m agents.run_demo --llm live
```

For repeatable testing:

```powershell
python -m agents.run_demo --llm mock
```

## Testing Requirements

Unit tests must not use paid LLM APIs.

Required tests:

- decision schema accepts valid trader decisions
- decision schema rejects invalid trader decisions
- decision schema accepts valid firm decisions
- decision schema rejects invalid firm decisions
- validator rejects unapproved assets
- validator rejects oversized trades
- validator rejects missing required action fields
- trader agent with mock LLM submits valid trade intent
- trader agent with mock LLM does not update portfolio after rejection
- firm agent with mock LLM submits valid dividend intent
- execution layer confirms only receipts with expected events

Integration tests should show that even if the mock LLM proposes a non-compliant action, smart contracts reject the transaction or local validation prevents submission.

## Security and Safety Notes

- Never commit real private keys or API keys.
- Use funded Sepolia testnet wallets for the main demo.
- Treat LLM output as untrusted input.
- Keep contract checks complete even if Python validation already checks the same rule.
- Log enough data to audit each agent action: observation summary, decision JSON, transaction hash, receipt status, and event verification.
- Use Hardhat local accounts only for unit tests and development dry runs.
