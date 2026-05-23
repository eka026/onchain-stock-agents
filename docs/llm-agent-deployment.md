# LLM Agent Deployment Design

## Purpose

This project deploys autonomous LLM-based trader and liquidity-provider agents as off-chain services for a news-driven multi-pool AMM simulation.

Agents can observe news and market state, then propose actions. They cannot bypass policy or mutate market state directly. All economically meaningful actions go through wallet-signed transactions and Solidity contract checks.

Core claim:

```text
LLM agents submit market intent through wallet-signed transactions, while Solidity contracts enforce approved tokens, swap limits, spending limits, liquidity limits, fee-withdrawal limits, fees, slippage checks, deadlines, and atomic settlement.
```

## Deployment Topology

```text
Sepolia or Local Hardhat Node
  - shared AgentPolicy
  - shared or repeated MockERC20 USD
  - one stock-like MockERC20 per market
  - one LPToken per AMM pool
  - one FeeVault per AMM pool
  - one AMMPool per stock/USD pair

News Feed
  - raw news dataset
  - scenario config
  - deterministic event schedule

Trader Agent Service(s)
  - trader wallet private key
  - LLM or mock decision client
  - Web3 RPC client
  - scenario metadata
  - local portfolio cache

LP Agent Service(s)
  - LP wallet private key
  - LLM or mock decision client
  - Web3 RPC client
  - scenario metadata
  - local portfolio cache
```

Each AMM pool remains a simple two-token contract. Multi-market behavior comes from deploying multiple pools and letting agents select a `pool_id` from scenario metadata.

## Compliance Model

The system has three decision layers:

```text
LLM decision: proposes intent
Python validator: rejects malformed or obviously invalid intent
Smart contracts: enforce final compliance
```

Examples:

- If a trader LLM chooses an unknown `pool_id`, Python rejects it.
- If a trader LLM chooses a token that is not in the selected pool, Python rejects it.
- If a trader LLM proposes an unapproved token, `AgentPolicy` rejects it.
- If a trader LLM exceeds its swap or spending limits, `AgentPolicy` rejects it.
- If an LP LLM exceeds liquidity or fee-withdrawal limits, `AgentPolicy` rejects it.
- If a swap would produce less than `minAmountOut`, `AMMPool` rejects it.
- If a transaction is reverted or missing the expected event, local portfolio state is not confirmed.

## Runtime Configuration

Use `.env` for wallet/model/provider configuration:

```text
SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
DEPLOYER_PRIVATE_KEY=0x...
SCENARIO_PATH=data/scenarios/demo.json

TRADER_PRIVATE_KEYS=0x...,0x...
TRADER_MODELS=gemini-2.0-flash-lite,gpt-4o-mini

LP_PRIVATE_KEYS=0x...
LP_MODELS=gemini-2.0-flash-lite

GOOGLE_API_KEY=...
GROQ_API_KEY=...
OPENAI_API_KEY=...
```

Use scenario files for market metadata:

```text
data/scenarios/demo.json
```

Scenario files define available tokens, deployed policy address, pool addresses, LP token addresses, vault addresses, news schedule settings, and the raw news file. They must not label news with sentiment, impact, or recommended trades.

## Agent Service Loop

Each deployed service follows the same loop:

```text
1. Load .env, scenario config, ABIs, and wallet.
2. Read current chain state through Web3.
3. Receive the current news broadcast, if any.
4. Build a compact observation.
5. Call the configured LLM or mock client.
6. Parse JSON into a Pydantic decision model.
7. Run local validation against scenario metadata and obvious policy constraints.
8. Submit a wallet-signed transaction when needed.
9. Wait for transaction receipt.
10. Verify status and expected event.
11. Update local portfolio only after confirmation.
12. Log observation summary, decision, tx hash, receipt status, and event result.
```

## Trader Agent

Trader observations should include:

- current raw news item;
- available token metadata;
- available pool metadata;
- reserves and spot price for relevant pools;
- own token balances;
- approved token status;
- swap limit and remaining spending estimate;
- recent swap events;
- optional trader profile.

Supported actions:

```text
SWAP
HOLD
```

Decision shape:

```json
{
  "action": "SWAP",
  "pool_id": "NVDA-USD",
  "token_in": "USD",
  "amount_in": 1000000000000000000,
  "reason": "The news appears positive for Nvidia, so I am buying NVDA with USD."
}
```

The execution layer maps this to the pool address from `pool_id`, computes conservative slippage fields, and submits:

```text
AMMPool.swap(tokenInAddress, amountIn, minAmountOut, deadline)
```

`HOLD` submits no transaction.

## LP Agent

LP observations should include:

- available pool metadata;
- reserves and spot price;
- own token balances;
- own LP token balances;
- accumulated fee state;
- LP policy limits;
- recent volume or swap activity.

Supported actions:

```text
ADD_LIQUIDITY
REMOVE_LIQUIDITY
COLLECT_FEES
HOLD
```

Example liquidity decision:

```json
{
  "action": "ADD_LIQUIDITY",
  "pool_id": "NVDA-USD",
  "amount_a": 1000000000000000000,
  "amount_b": 1000000000000000000,
  "lp_shares": 0,
  "reason": "The pool has enough activity to justify adding liquidity."
}
```

The execution layer maps valid decisions to:

```text
AMMPool.addLiquidity(amountA, amountB, minLpShares)
AMMPool.removeLiquidity(lpShares)
FeeVault.collectFees(lpShares)
```

## News Feed

News records are raw and unlabeled:

```json
{
  "id": "news-001",
  "headline": "Nvidia reports stronger than expected data center revenue",
  "body": "Nvidia announced quarterly revenue above analyst expectations, citing continued demand for AI infrastructure."
}
```

Not allowed in news records:

```text
token
sentiment
impact
trade_hint
```

The LLM must infer relevance and direction from the news text and available market metadata.

## Failure Handling

- LLM timeout: choose `HOLD`.
- Invalid JSON: reject and choose `HOLD`.
- Schema validation failure: reject and choose `HOLD`.
- Unknown pool: reject locally.
- Token not in selected pool: reject locally.
- Local policy estimate failure: do not submit a transaction.
- Transaction revert: mark `REJECTED`.
- Expected event missing: mark `REJECTED`.
- Receipt timeout: mark `PENDING`.

Rejected and pending actions must not mutate confirmed local portfolio state.

## Demo Commands

Expected service commands:

```powershell
python -m agents.trader_agent --index 0 --once
python -m agents.trader_agent --index 1 --interval 15
python -m agents.lp_agent --index 0 --once
python -m agents.run_demo --scenario data/scenarios/demo.json --llm mock
```

For unit tests, use mock LLM clients only. Live provider calls are optional and must not be required for CI or classroom grading.

## Scope Notes

- Keep `FeeVault` simple for the prototype.
- Use multiple two-token pools instead of a multi-token AMM contract.
- Keep prompts short and force structured JSON output.
- Use events as the bridge between on-chain success and local portfolio confirmation.
- Never commit private keys or paid API keys.
