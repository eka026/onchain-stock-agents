import { ethers } from "hardhat";

const CONFIG = {
  paymentInitialSupply: 1_000_000n,
  stockMaxSupply: 500_000n,
  initialFirmShares: 10_000n,
  initialSellerAgentShares: 10_000n,
  initialSellerAgentPayment: 50_000n,
  initialBuyerAgentPayment: 50_000n,
  stockTokenMaxTradeSize: 500n,
  agentMaxTradeSize: 500n,
  agentSpendingLimit: 100_000n,
  firmDividendBudget: 10_000n,
  policyWindowDuration: 3_600n
};

function stringifyDeployment(value: unknown) {
  return JSON.stringify(
    value,
    (_key, item) => (typeof item === "bigint" ? item.toString() : item),
    2
  );
}

export async function deployLocalContracts() {
  const [deployer, firm, sellerAgent, buyerAgent] = await ethers.getSigners();

  const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
  const policy = await AgentPolicy.deploy();

  const MockERC20 = await ethers.getContractFactory("MockERC20");
  const paymentToken = await MockERC20.deploy("USD Coin", "USDC", CONFIG.paymentInitialSupply);

  const StockToken = await ethers.getContractFactory("StockToken");
  const stockToken = await StockToken.deploy("ACME Corp", "ACME", firm.address, CONFIG.stockMaxSupply);

  const Exchange = await ethers.getContractFactory("Exchange");
  const exchange = await Exchange.deploy(await policy.getAddress(), await paymentToken.getAddress());

  const DividendVault = await ethers.getContractFactory("DividendVault");
  const dividendVault = await DividendVault.deploy(
    await policy.getAddress(),
    await paymentToken.getAddress()
  );

  const contracts = {
    paymentToken: await paymentToken.getAddress(),
    stockToken: await stockToken.getAddress(),
    policy: await policy.getAddress(),
    exchange: await exchange.getAddress(),
    dividendVault: await dividendVault.getAddress()
  };

  await policy.setTokenPolicy(contracts.stockToken, true, CONFIG.stockTokenMaxTradeSize, false);
  await policy.setTraderPolicy(
    firm.address,
    true,
    CONFIG.agentMaxTradeSize,
    CONFIG.agentSpendingLimit,
    CONFIG.policyWindowDuration
  );
  await policy.setTraderPolicy(
    sellerAgent.address,
    true,
    CONFIG.agentMaxTradeSize,
    CONFIG.agentSpendingLimit,
    CONFIG.policyWindowDuration
  );
  await policy.setTraderPolicy(
    buyerAgent.address,
    true,
    CONFIG.agentMaxTradeSize,
    CONFIG.agentSpendingLimit,
    CONFIG.policyWindowDuration
  );
  await policy.setDividendPolicy(
    firm.address,
    true,
    CONFIG.firmDividendBudget,
    CONFIG.policyWindowDuration
  );
  await policy.setRecorder(contracts.exchange, true);
  await policy.setRecorder(contracts.dividendVault, true);

  await stockToken.connect(firm).mint(firm.address, CONFIG.initialFirmShares);
  await stockToken.connect(firm).mint(sellerAgent.address, CONFIG.initialSellerAgentShares);
  await paymentToken.transfer(sellerAgent.address, CONFIG.initialSellerAgentPayment);
  await paymentToken.transfer(buyerAgent.address, CONFIG.initialBuyerAgentPayment);

  await stockToken.connect(firm).approve(contracts.exchange, ethers.MaxUint256);
  await stockToken.connect(sellerAgent).approve(contracts.exchange, ethers.MaxUint256);
  await paymentToken.connect(sellerAgent).approve(contracts.exchange, ethers.MaxUint256);
  await paymentToken.connect(buyerAgent).approve(contracts.exchange, ethers.MaxUint256);
  await paymentToken.connect(firm).approve(contracts.dividendVault, ethers.MaxUint256);

  return {
    network: "localhost",
    contracts,
    actors: {
      deployer: deployer.address,
      firm: firm.address,
      sellerAgent: sellerAgent.address,
      buyerAgent: buyerAgent.address
    },
    config: CONFIG,
    instances: {
      paymentToken,
      stockToken,
      policy,
      exchange,
      dividendVault
    }
  };
}

async function main() {
  const deployment = await deployLocalContracts();
  const { instances: _instances, ...jsonDeployment } = deployment;

  console.log(stringifyDeployment(jsonDeployment));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
