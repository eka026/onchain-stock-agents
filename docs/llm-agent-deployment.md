# LLM Agent Deployment Design

## Purpose

This project deploys autonomous LLM-based trader and liquidity-provider agents as off-chain services that participate in an on-chain AMM. Agents can decide what they want to do, but they cannot bypass ecosystem rules. Smart contracts are the compliance layer and the final authority for every market action.

The core claim is:

> LLM agents submit market intent through wallet-signed transactions, while Solidity contracts enforce approved tokens, swap limits, spending limits, liquidity limits, fee-withdrawal limits, and atomic settlement.

## Deployment Topology

```text
Sepolia or Local Hardhat Node
  - MockERC20 token A
  - MockERC20 token B
  - AgentPolicy
  - LPToken
  - AMMPool
  - FeeVault

LP Agent Service
  - LP wallet private key
  - LLM decision loop
  - Web3 RPC client
  - local portfolio tracker

Trader Agent Service
  - trader wallet private key
  - LLM decision loop
  - Web3 RPC client
  - local portfolio tracker
```

Each agent module can run as a real process. For the testnet demo, all processes connect to a Sepolia RPC endpoint and use funded testnet wallets. Contracts can be deployed from Remix IDE or `scripts/deploy.ts`, then the resulting addresses are copied into `.env`.

## Compliance Model

The system has three decision layers:

```text
LLM decision: proposes intent
Python validator: rejects malformed or obviously invalid intent
Smart contracts: enforce final compliance
```

Examples:

- If a trader LLM proposes an unapproved token, `AgentPolicy` rejects it.
- If a trader LLM proposes a swap above its max size, `AgentPolicy` rejects it.
- If a trader LLM exceeds its spending limit, `AgentPolicy` rejects it.
- If an LP LLM proposes too much liquidity add/remove, `AgentPolicy` rejects it.
- If an LP LLM exceeds its fee-withdrawal limit, `AgentPolicy` rejects it.
- If a swap would produce less than the submitted `minAmountOut`, `AMMPool` rejects it.

Local portfolios update only after receipt confirmation and expected event verification.

## Runtime Configuration

Use `.env` for local deployment configuration:

```text
SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
DEPLOYER_PRIVATE_KEY=0x...
TRADER_PRIVATE_KEYS=0x...,0x...
TRADER_MODELS=gemini-2.0-flash-lite,gpt-4o-mini
LP_PRIVATE_KEYS=0x...
LP_MODELS=gemini-2.0-flash-lite

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

Do not commit real API keys or private keys. For the Hardhat demo, use local deterministic accounts only.

## Agent Service Loop

Each deployed service follows the same loop:

```text
1. Load environment and contract addresses.
2. Load the agent wallet.
3. Read chain state through Web3.
4. Build a compact observation.
5. Call the configured low-cost LLM API.
6. Parse structured JSON into a decision model.
7. Run local validation.
8. Submit a wallet-signed transaction when needed.
9. Wait for transaction receipt.
10. Verify the expected contract event.
11. Update local memory or portfolio only after confirmation.
12. Log decision, transaction hash, receipt status, and event result.
```

## Trader Agent

The trader agent observes token balances, reserves, spot price, approved token status, maximum swap size, spending limit, spending used, and recent swap events.

Allowed trader actions:

- `SWAP_A_FOR_B`
- `SWAP_B_FOR_A`
- `HOLD`

Swap decisions must include `amountIn`, `minAmountOut`, and `deadline`. The service maps valid swap decisions to `AMMPool.swap(tokenIn, amountIn, minAmountOut, deadline)`.

## LP Agent

The LP agent observes token balances, LP token balance, reserves, accumulated fees, liquidity policy limits, and fee-withdrawal policy state.

Allowed LP actions:

- `ADD_LIQUIDITY`
- `REMOVE_LIQUIDITY`
- `COLLECT_FEES`
- `HOLD`

Liquidity-add decisions must include balanced token amounts for the current reserve ratio and a `minLpShares` value. The service maps valid add decisions to `AMMPool.addLiquidity(amountA, amountB, minLpShares)`.
