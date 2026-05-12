# Milestone 2 Smart Contracts

## Purpose

Milestone 2 adds the first enforceable on-chain rules for the stock market simulation. The important design choice is that LLM agents never receive direct authority over market state. They can only submit wallet-signed transactions, and Solidity contracts decide whether those transactions are allowed.

This milestone implements two contracts:

- `AgentPolicy.sol`: the on-chain compliance layer for autonomous agents.
- `StockToken.sol`: an ERC-20 share token with firm-only issuance and a hard supply cap.

The exchange and dividend vault are intentionally left for Milestone 3. Milestone 2 only defines the policy and share-token rules that those later contracts will depend on.

## `AgentPolicy.sol`

`AgentPolicy` is the rulebook for trading and dividend behavior. It does not transfer tokens and does not settle trades. Instead, it validates whether a proposed action is allowed and records usage after another authorized contract completes the action.

The robust policy layer includes four categories of rules.

## Asset Policy

Asset policy controls which stock tokens can be traded.

Tracked state:

```solidity
mapping(address => bool) public isTokenApproved;
mapping(address => uint256) public tokenMaxTradeSize;
mapping(address => bool) public isTokenTradingPaused;
```

This supports:

- approving or rejecting individual stock tokens;
- setting a token-level maximum trade size;
- pausing trading for a specific token without removing its configuration.

The owner configures asset policy with:

```solidity
setTokenPolicy(address token, bool approved, uint256 maxTradeSize, bool paused)
```

## Trader Policy

Trader policy controls what each trader wallet is allowed to do.

Tracked state:

```solidity
struct TraderPolicy {
    bool enabled;
    uint256 maxTradeSize;
    uint256 spendingLimit;
    uint256 spentAmount;
    uint256 windowStart;
    uint256 windowDuration;
}
```

This supports:

- enabling or disabling a trader wallet;
- setting a maximum shares-per-trade limit;
- setting a spending limit;
- enforcing that spending limit inside a rolling time window.

The owner configures trader policy with:

```solidity
setTraderPolicy(
    address trader,
    bool enabled,
    uint256 maxTradeSize,
    uint256 spendingLimit,
    uint256 windowDuration
)
```

`validateTrade(...)` checks:

- the stock token is approved;
- the stock token is not paused;
- the trader is enabled;
- the trade does not exceed the trader-level max trade size;
- the trade does not exceed the token-level max trade size;
- the payment amount does not exceed the trader spending limit for the current window.

## Spending Recording

`AgentPolicy` separates validation from accounting. Later, `Exchange.sol` should call `recordSpending(...)` only after a successful buy settlement.

Only approved recorder contracts may record spending:

```solidity
mapping(address => bool) public isRecorder;
```

The owner configures recorders with:

```solidity
setRecorder(address recorder, bool approved)
```

This prevents arbitrary wallets from increasing another trader's spent amount.

## Dividend Policy

Dividend policy controls how much each firm can pay out during a time window.

Tracked state:

```solidity
struct DividendPolicy {
    bool enabled;
    uint256 budget;
    uint256 paidAmount;
    uint256 windowStart;
    uint256 windowDuration;
}
```

This supports:

- enabling or disabling dividend payments for a firm;
- setting a dividend budget;
- enforcing that budget inside a rolling time window.

The owner configures dividend policy with:

```solidity
setDividendPolicy(
    address firm,
    bool enabled,
    uint256 budget,
    uint256 windowDuration
)
```

Later, `DividendVault.sol` should call:

```solidity
validateDividend(address firm, uint256 amount)
recordDividend(address firm, uint256 amount)
```

The intended flow is:

1. `DividendVault` validates the proposed payout.
2. `DividendVault` transfers payment tokens to holders.
3. `DividendVault` records the payout in `AgentPolicy`.

## Window Behavior

Both trader spending and firm dividend budgets use windowed accounting.

If the current block timestamp is still inside the configured window, the stored usage value is active. If the window has expired, view helpers report usage as zero:

```solidity
currentSpentAmount(address trader)
currentDividendPaid(address firm)
```

When a recorder records spending or dividends after expiration, the contract starts a new window at the current block timestamp.

This is more useful than a lifetime spending limit because agent wallets can be given periodic budgets, such as daily trade limits or weekly dividend limits.

## `StockToken.sol`

`StockToken` represents shares of one listed firm. It uses OpenZeppelin ERC-20 behavior for balances, transfers, and allowances.

Additional state:

```solidity
address public immutable firm;
uint256 public immutable maxSupply;
```

Only the configured firm wallet can mint:

```solidity
function mint(address to, uint256 amount) external
```

Minting reverts if:

- the caller is not the firm;
- minting would push total supply above `maxSupply`;
- the constructor is given a zero firm address;
- the constructor is given a zero supply cap.

`StockToken` does not know about policy, exchanges, dividends, or LLM agents. It only enforces share issuance authority and supply cap.

## How Milestone 3 Should Use This

`Exchange.sol` should:

1. call `AgentPolicy.validateTrade(...)`;
2. transfer payment tokens and stock tokens atomically;
3. call `AgentPolicy.recordSpending(...)` after a successful buy;
4. emit `TradeSettled`.

`DividendVault.sol` should:

1. call `AgentPolicy.validateDividend(...)`;
2. check firm reserve balance;
3. transfer payment tokens to holders;
4. call `AgentPolicy.recordDividend(...)`;
5. emit `DividendPaid`.

The policy contract should remain the shared compliance layer, while settlement contracts handle movement of assets.

## Verification

Focused Milestone 2 verification:

```powershell
npm test -- test/AgentPolicy.test.ts test/StockToken.test.ts
```

Full Solidity verification:

```powershell
npm test
npm run compile
```

Current tests cover:

- token policy storage;
- token pause rejection;
- disabled trader rejection;
- trader max trade size rejection;
- token max trade size rejection;
- spending-limit window behavior;
- recorder-only spending and dividend accounting;
- dividend budget window behavior;
- owner-only policy configuration;
- firm-only stock minting;
- supply-cap enforcement;
- invalid stock-token constructor arguments.
