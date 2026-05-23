# Archived Milestone 2 Smart Contracts Note

This file previously described the old stock-token, exchange, and dividend-vault design. That design has been replaced by the news-driven multi-pool AMM architecture.

Current contract focus:

- `AgentPolicy.sol`: token approvals, trader swap limits, LP liquidity limits, LP fee-withdrawal limits, recorder authorization.
- `LPToken.sol`: pool-controlled LP share minting and burning.
- `AMMPool.sol`: two-token constant-product pool with fees, slippage checks, deadlines, and policy enforcement.
- `FeeVault.sol`: intentionally simple fee accumulation and proportional LP fee collection.
- `contracts/test/MockERC20.sol`: mock USD and stock-like demo tokens.

Use these current docs instead:

- `docs/on-chain-stock-market-implementation-plan.md`
- `docs/llm-agent-deployment.md`
- `docs/demo-checklist.md`
- `docs/2026-05-23-news-driven-trading-design.md`

Historical note:

The old stock-market design used `StockToken`, `Exchange`, and `DividendVault`. Those components are no longer part of the implementation target for this project.
