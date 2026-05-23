# onchain-stock-agents

A blockchain-based AMM simulation where autonomous trader and liquidity-provider agents interact with Solidity contracts that enforce token approvals, swap limits, liquidity limits, fee-withdrawal limits, swap fees, and atomic settlement.

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

## Testnet contract deployment

The contracts are intended to run against a public test network such as Sepolia. Hardhat is used for compilation, tests, ABI export, and optional scripted deployment. Runtime agents should point at a testnet RPC URL.

### Option A: Deploy with Remix IDE

Compile locally and export fresh ABIs:

```powershell
npm run compile
npm run export:abis
```

In Remix, deploy the contracts to Sepolia in this order:

1. `MockERC20` from `contracts/test/MockERC20.sol` for token A
2. `MockERC20` from `contracts/test/MockERC20.sol` for token B
3. `AgentPolicy`
4. `LPToken`
5. `FeeVault`, using the policy, token A, token B, and LP token addresses
6. `AMMPool`, using the policy, token A, token B, LP token, and fee vault addresses

After deployment, wire the pool:

```text
LPToken.setPool(POOL_ADDRESS)
FeeVault.setPool(POOL_ADDRESS)
```

Configure the market from the policy owner wallet:

```text
AgentPolicy.setTokenApproval(TOKEN_A_ADDRESS, true)
AgentPolicy.setTokenApproval(TOKEN_B_ADDRESS, true)
AgentPolicy.setTraderPolicy(TRADER_ADDRESS, true, 1000000000000000000000, 100000000000000000000000, 3600)
AgentPolicy.setLPPolicy(LP_ADDRESS, true, 100000000000000000000000, 100000000000000000000000, 100000000000000000000000, 3600)
AgentPolicy.setRecorder(POOL_ADDRESS, true)
AgentPolicy.setRecorder(VAULT_ADDRESS, true)
```

Fund LP and trader wallets with token A and token B, then approve the pool from each funded wallet:

```text
MockERC20.transfer(LP_ADDRESS, AMOUNT)
MockERC20.transfer(TRADER_ADDRESS, AMOUNT)
MockERC20.approve(POOL_ADDRESS, MAX_UINT256)
```

Paste the deployed addresses into `.env`:

```env
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
```

### Option B: Deploy with Hardhat

```powershell
npm run deploy:sepolia
```

For scripted deployment, `.env` must include `SEPOLIA_RPC_URL`, `DEPLOYER_PRIVATE_KEY`, at least one `TRADER_PRIVATE_KEYS` entry, and at least one `LP_PRIVATE_KEYS` entry. The deployer and setup wallets need Sepolia ETH for gas.

The deploy script prints JSON for Python agents to consume. It includes deployed contract addresses, configured actor accounts, and the policy limits used during setup.
