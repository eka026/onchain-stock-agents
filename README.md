# onchain-stock-agents

A news-driven multi-pool AMM simulation where autonomous trader and liquidity-provider agents interact with Solidity contracts that enforce token approvals, swap limits, liquidity limits, fee-withdrawal limits, swap fees, and atomic settlement.

The core AMM contract is intentionally a simple two-token pool. Multi-market behavior is modeled by deploying one pool per stock/USD pair and giving agents scenario metadata so they can choose which pool to trade after receiving raw news.

## Local setup

Install Node and Python dependencies:

```powershell
npm install
python -m pip install -r requirements.txt
```

Verify the project:

```powershell
npm run compile
npm test
python -m pytest
```

The news-driven demo uses:

```text
data/news.json
data/scenarios/demo.json
```

News records are raw and unlabeled. Scenario files define available tokens and pools, not sentiment or trade hints.

## Testnet contract deployment

The contracts are intended to run against a public test network such as Sepolia. Hardhat is used for compilation, tests, ABI export, and scripted deployment. Runtime agents should point at a testnet RPC URL and a scenario file containing deployed addresses.

`scripts/deploy.ts` is scenario-driven. It reads `data/scenarios/demo.json`, deploys the shared policy, all mock tokens, and one `LPToken`/`FeeVault`/`AMMPool` set per stock/USD pair, configures policies and approvals for every configured agent wallet, seeds initial pool liquidity, and writes a runtime scenario file such as `data/scenarios/sepolia.json`.

### Option A: Deploy with Remix IDE

Compile locally and export fresh ABIs:

```powershell
npm run compile
npm run export:abis
```

In Remix, deploy the contracts to Sepolia in this order for each stock/USD pool:

1. `MockERC20` from `contracts/test/MockERC20.sol` for token A
2. `MockERC20` from `contracts/test/MockERC20.sol` for token B
3. `AgentPolicy`
4. `LPToken`
5. `FeeVault`, using the policy, token A, token B, and LP token addresses
6. `AMMPool`, using the policy, token A, token B, LP token, and fee vault addresses

After deployment, wire each pool:

```text
LPToken.setPool(<pool address for this pair>)
FeeVault.setPool(<pool address for this pair>)
```

Configure the market from the policy owner wallet:

```text
AgentPolicy.setTokenApproval(<USD token address>, true)
AgentPolicy.setTokenApproval(<stock token address>, true)
AgentPolicy.setTraderPolicy(TRADER_ADDRESS, true, 1000000000000000000000, 100000000000000000000000, 3600)
AgentPolicy.setLPPolicy(LP_ADDRESS, true, 100000000000000000000000, 100000000000000000000000, 100000000000000000000000, 3600)
AgentPolicy.setRecorder(<pool address for this pair>, true)
AgentPolicy.setRecorder(<vault address for this pair>, true)
```

Fund LP and trader wallets with token A and token B, then approve the pool from each funded wallet:

```text
MockERC20.transfer(LP_ADDRESS, AMOUNT)
MockERC20.transfer(TRADER_ADDRESS, AMOUNT)
MockERC20.approve(<pool address for this pair>, MAX_UINT256)
```

Paste runtime settings into `.env`:

```env
RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
DEPLOYER_PRIVATE_KEY=0x...
DEPLOY_SCENARIO_TEMPLATE=data/scenarios/demo.json
DEPLOY_OUTPUT_SCENARIO=data/scenarios/sepolia.json
SCENARIO_PATH=data/scenarios/sepolia.json

TRADER_PRIVATE_KEYS=0x...,0x...
TRADER_MODELS=gemini-2.0-flash-lite,gpt-4o-mini
LP_PRIVATE_KEYS=0x...
LP_MODELS=gemini-2.0-flash-lite
```

Paste deployed market addresses into the scenario file, not `.env`:

```json
{
  "policy_address": "0x...",
  "tokens": [
    { "symbol": "USD", "address": "0x..." },
    { "symbol": "NVDA", "address": "0x..." }
  ],
  "pools": [
    {
      "id": "NVDA-USD",
      "base_symbol": "NVDA",
      "quote_symbol": "USD",
      "pool_address": "0x...",
      "lp_token_address": "0x...",
      "vault_address": "0x..."
    }
  ]
}
```

### Option B: Deploy with Hardhat

```powershell
npm run compile
npm run deploy:sepolia
```

For scripted deployment, `.env` must include `RPC_URL` (or legacy `SEPOLIA_RPC_URL`), `DEPLOYER_PRIVATE_KEY`, at least two `TRADER_PRIVATE_KEYS` entries, and at least one `LP_PRIVATE_KEYS` entry. The deployer and setup wallets need Sepolia ETH for gas because deployment, ERC20 approvals, and initial liquidity all send transactions.

The deploy script writes the runtime scenario path from `DEPLOY_OUTPUT_SCENARIO` and prints JSON for Python agents to consume. It includes deployed contract addresses, configured actor accounts, and the policy limits used during setup.

After Sepolia deployment, run the deterministic mock demo first:

```powershell
python -m agents.run_demo --scenario data/scenarios/sepolia.json --llm mock --low-gas
```

`--low-gas` skips the LP lifecycle and policy-negative scenarios and submits only the first trader broadcast transaction. Use the full command without `--low-gas` only when you intentionally want the complete demo flow and have enough Sepolia ETH for extra transactions.
