# News-Driven Multi-Pool Trading Design

## Goal

Extend the AMM agent simulation so trader agents receive reproducible news broadcasts and decide whether to trade based on the news, their trading profile, wallet state, and AMM market state.

The news dataset must remain raw and unlabeled. It must not include token symbols, sentiment, impact scores, trade hints, or any field that tells an agent how to interpret the event.

## Raw News Dataset

Store raw news records in `data/news.json`.

Each record contains only identifying and text fields:

```json
[
  {
    "id": 1,
    "headline": "Large companies accelerate cloud migration after budget freeze ends",
    "body": "Procurement teams reopened infrastructure projects that had been delayed for two quarters, with priority given to data storage, security monitoring, and collaboration tools."
  }
]
```

The agent is responsible for deciding whether the news is relevant to any tradable token, whether it is positive or negative, and whether it should trade.

## Scenario Config

Store reproducible run settings in a separate scenario file such as `data/scenarios/demo.json`.

The scenario controls scheduling and market metadata, not news interpretation:

```json
{
  "seed": 438,
  "news_file": "data/news.json",
  "policy_address": "0x...",
  "min_interval_ticks": 2,
  "max_interval_ticks": 5,
  "max_events": 6,
  "broadcast_to_all_traders": true,
  "tokens": [
    { "symbol": "USD", "address": "0x..." },
    { "symbol": "TECH", "address": "0x..." },
    { "symbol": "FIN", "address": "0x..." },
    { "symbol": "HLTH", "address": "0x..." },
    { "symbol": "CSMR", "address": "0x..." },
    { "symbol": "MLTRY", "address": "0x..." },
    { "symbol": "INDS", "address": "0x..." },
    { "symbol": "ENRG", "address": "0x..." },
    { "symbol": "MATL", "address": "0x..." },
    { "symbol": "COMM", "address": "0x..." },
    { "symbol": "REIT", "address": "0x..." }
  ],
  "pools": [
    {
      "id": "TECH-USD",
      "base_symbol": "TECH",
      "quote_symbol": "USD",
      "pool_address": "0x...",
      "lp_token_address": "0x...",
      "vault_address": "0x..."
    },
    {
      "id": "FIN-USD",
      "base_symbol": "FIN",
      "quote_symbol": "USD",
      "pool_address": "0x...",
      "lp_token_address": "0x...",
      "vault_address": "0x..."
    },
    {
      "id": "HLTH-USD",
      "base_symbol": "HLTH",
      "quote_symbol": "USD",
      "pool_address": "0x...",
      "lp_token_address": "0x...",
      "vault_address": "0x..."
    }
  ]
}
```

The token and pool metadata tells agents what markets exist. It does not map a news item to a token.

## Market Architecture

Use multiple two-token AMM pools instead of rewriting the smart contract as a multi-token pool.

Each stock-like token trades against a shared mock USD token:

```text
TECH / USD
FIN / USD
HLTH / USD
CSMR / USD
MLTRY / USD
INDS / USD
ENRG / USD
MATL / USD
COMM / USD
REIT / USD
```

This matches the existing `AMMPool` contract, which supports exactly two ERC-20 tokens. Supporting many stock tokens means deploying multiple `AMMPool` instances, one per pair.

## News Dispatcher

Add `agents/news_feed.py`.

Responsibilities:

- Load raw news from `data/news.json`.
- Load scenario settings from `data/scenarios/demo.json`.
- Use the scenario seed for deterministic event selection and timing.
- Generate deterministic intervals between news events.
- Broadcast the same news item to all trader agents at the same simulation tick.
- Keep news delivery reproducible: the same scenario file and seed produce the same event order and timing.

## Trader Observation

Extend trader observations so each trader receives:

- Current broadcast news item.
- Available token metadata.
- Available pool metadata.
- Relevant on-chain state for each pool, including reserves and spot price.
- Own token balances.
- Own policy limits and remaining spend.
- Own trading profile.

The prompt should make clear that the news is unlabeled and that the trader must infer relevance and direction.

## Trader Decision Schema

For multiple pools, a trader decision should include the selected pool:

```json
{
  "action": "SWAP",
  "pool_id": "TECH-USD",
  "token_in": "USD",
  "amount_in": 1000000000000000000,
  "reason": "The news appears relevant to enterprise software and computing infrastructure, so I am increasing exposure to that market."
}
```

Supported actions:

- `HOLD`
- `SWAP`

Validation rules:

- `HOLD` submits no transaction.
- `SWAP` requires a known `pool_id`.
- `token_in` must be one of the two tokens in that pool.
- `amount_in` must be positive and within local policy estimates.
- Smart contracts remain the final authority and may still reject the transaction.

## Data Flow

1. Scenario runner loads the scenario and news dataset.
2. News dispatcher deterministically schedules news events.
3. At each scheduled tick, the dispatcher broadcasts one raw news item to all traders.
4. Each trader observes the same news plus its own balances, policies, profile, and market state.
5. Each trader asks its LLM for a structured decision.
6. Local validation rejects malformed or obviously invalid decisions.
7. Valid swaps are submitted to the selected AMM pool.
8. Receipt verification updates local portfolio state only after confirmed on-chain success and expected events.
9. Reverted or missing transactions leave local portfolio state unchanged.

## Error Handling

- Invalid news JSON fails scenario startup.
- Invalid scenario JSON fails scenario startup.
- Unknown pool IDs from an LLM decision are rejected locally.
- Unknown token symbols or token addresses are rejected locally.
- Reverts are treated as rejected executions and do not mutate confirmed portfolio state.
- Missing receipts are treated as pending until timeout, then left unconfirmed.

## Testing

Add tests for:

- Deterministic news order and interval generation for a fixed seed.
- Broadcast delivery of the same news item to all traders at a tick.
- Raw news schema rejection when interpretation fields such as `token`, `sentiment`, or `impact` are present.
- Trader decision validation for known and unknown pool IDs.
- Trader decision validation for valid and invalid `token_in` values.
- Portfolio state remaining unchanged after rejected or reverted swaps.

## Implementation Scope

This design does not require changing the current `AMMPool` contract for a multi-token pool. The first implementation should deploy or configure multiple existing two-token pools and teach the Python agent layer to select among them.

