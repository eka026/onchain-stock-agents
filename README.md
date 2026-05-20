# onchain-stock-agents

A blockchain-based stock market simulation where autonomous trading agents interact with Solidity smart contracts that enforce asset approval, trade limits, share issuance caps, dividends, and atomic settlement.

## Local setup

Install Node and Python dependencies:

```powershell
npm install
python -m pip install -r requirements.txt
```

Verify the Hardhat scaffold:

```powershell
npm run compile
```

## Testnet contract deployment

The contracts are intended to run against a public test network such as Sepolia. Hardhat is still used for compilation, tests, ABI export, and optional scripted deployment, but the runtime agents should point at a testnet RPC URL.

### Option A: Deploy with Remix IDE

Compile the contracts locally and export fresh ABIs:

```powershell
npm run compile
npm run export:abis
```

In Remix, deploy the contracts to Sepolia in this order:

1. `AgentPolicy`
2. `MockERC20` from `contracts/test/MockERC20.sol` for demo payment tokens, unless you already have a Sepolia ERC-20 payment token
3. `StockToken`, using the firm wallet address as `owner_`
4. `Exchange`, using the deployed policy and payment token addresses
5. `DividendVault`, using the deployed policy and payment token addresses

After deployment, paste the resulting addresses into `.env`:

```env
SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
FIRM_PRIVATE_KEY=0x...
TRADER_PRIVATE_KEYS=0x...,0x...

PAYMENT_TOKEN_ADDRESS=0x...
STOCK_TOKEN_ADDRESS=0x...
POLICY_ADDRESS=0x...
EXCHANGE_ADDRESS=0x...
VAULT_ADDRESS=0x...
```

Configure the market from Remix by calling:

```text
AgentPolicy.setTokenPolicy(STOCK_TOKEN_ADDRESS, true, 500, false)
AgentPolicy.setTraderPolicy(FIRM_ADDRESS, true, 500, 100000, 3600)
AgentPolicy.setTraderPolicy(TRADER_ADDRESS, true, 500, 100000, 3600)
AgentPolicy.setDividendPolicy(FIRM_ADDRESS, true, 10000, 3600)
AgentPolicy.setRecorder(EXCHANGE_ADDRESS, true)
AgentPolicy.setRecorder(VAULT_ADDRESS, true)
StockToken.mint(FIRM_ADDRESS, 10000)
StockToken.mint(TRADER_ADDRESS, 10000)
MockERC20.transfer(TRADER_ADDRESS, 50000)
StockToken.approve(EXCHANGE_ADDRESS, MAX_UINT256)
MockERC20.approve(EXCHANGE_ADDRESS, MAX_UINT256)
MockERC20.approve(VAULT_ADDRESS, MAX_UINT256)
```

Approvals must be submitted from the wallet that owns the tokens.

### Option B: Deploy with Hardhat

```powershell
npm run deploy:sepolia
```

For scripted deployment, `.env` must include `SEPOLIA_RPC_URL`, `DEPLOYER_PRIVATE_KEY`, `FIRM_PRIVATE_KEY`, and at least two comma-separated `TRADER_PRIVATE_KEYS`. The deployer and setup wallets need Sepolia ETH for gas.

The deploy script prints JSON for Python agents to consume. It includes deployed contract addresses, configured actor accounts, and the policy limits used during setup:

```json
{
  "network": "sepolia",
  "contracts": {
    "paymentToken": "0x...",
    "stockToken": "0x...",
    "policy": "0x...",
    "exchange": "0x...",
    "dividendVault": "0x..."
  },
  "actors": {
    "deployer": "0x...",
    "firm": "0x...",
    "sellerAgent": "0x...",
    "buyerAgent": "0x..."
  },
  "config": {
    "paymentInitialSupply": "1000000",
    "stockMaxSupply": "500000",
    "initialFirmShares": "10000",
    "initialSellerAgentShares": "10000",
    "initialSellerAgentPayment": "50000",
    "initialBuyerAgentPayment": "50000",
    "stockTokenMaxTradeSize": "500",
    "agentMaxTradeSize": "500",
    "agentSpendingLimit": "100000",
    "firmDividendBudget": "10000",
    "policyWindowDuration": "3600"
  }
}
```

The script approves the stock token, configures firm, seller-agent, and buyer-agent trade limits, configures the firm dividend budget, and authorizes both the exchange and dividend vault as policy recorders.
