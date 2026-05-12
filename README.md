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

Milestone 1 only sets up project tooling. Later milestones add Solidity contracts, deployment scripts, Python agents, and the reproducible end-to-end demo.
