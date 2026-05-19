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

## Local contract deployment

Start a local Hardhat node in one terminal:

```powershell
npm run node
```

Deploy and configure the local market contracts in another terminal:

```powershell
npm run deploy:local
```

The deploy script prints JSON for Python agents to consume. It includes deployed contract addresses, configured actor accounts, and the policy limits used during setup:

```json
{
  "network": "localhost",
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
