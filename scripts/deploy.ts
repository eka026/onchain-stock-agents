import { ethers, network } from "hardhat";

const CONFIG = {
  tokenInitialSupply: ethers.parseEther("1000000"),
  initialLpTokenA: ethers.parseEther("10000"),
  initialLpTokenB: ethers.parseEther("10000"),
  initialTraderTokenA: ethers.parseEther("1000"),
  initialTraderTokenB: ethers.parseEther("1000"),
  traderMaxSwapAmount: ethers.parseEther("1000"),
  traderSpendingLimit: ethers.parseEther("100000"),
  lpMaxLiquidityAdd: ethers.parseEther("100000"),
  lpMaxLiquidityRemove: ethers.parseEther("100000"),
  lpMaxFeeWithdrawal: ethers.parseEther("100000"),
  policyWindowDuration: 3_600n
};

function stringifyDeployment(value: unknown) {
  return JSON.stringify(
    value,
    (_key, item) => (typeof item === "bigint" ? item.toString() : item),
    2
  );
}

function requireEnv(key: string) {
  const value = process.env[key];
  if (!value) {
    throw new Error(`Missing required env var: ${key}`);
  }
  return value;
}

function getOptionalPrivateKeys(key: string) {
  return (process.env[key] ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

export async function deployContracts() {
  const [deployer, localLp, localTrader] = await ethers.getSigners();
  const isLocalNetwork = network.name === "hardhat" || network.name === "localhost";

  const lpWallet = isLocalNetwork
    ? localLp
    : new ethers.Wallet(getOptionalPrivateKeys("LP_PRIVATE_KEYS")[0] ?? requireEnv("LP_PRIVATE_KEYS"), ethers.provider);
  const traderWallet = isLocalNetwork
    ? localTrader
    : new ethers.Wallet(getOptionalPrivateKeys("TRADER_PRIVATE_KEYS")[0] ?? requireEnv("TRADER_PRIVATE_KEYS"), ethers.provider);

  const MockERC20 = await ethers.getContractFactory("MockERC20");
  const tokenA: any = await MockERC20.deploy("Token A", "TKA", CONFIG.tokenInitialSupply);
  const tokenB: any = await MockERC20.deploy("Token B", "TKB", CONFIG.tokenInitialSupply);

  const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
  const policy: any = await AgentPolicy.deploy();

  const LPToken = await ethers.getContractFactory("LPToken");
  const lpToken: any = await LPToken.deploy("AMM LP", "ALP");

  const FeeVault = await ethers.getContractFactory("FeeVault");
  const vault: any = await FeeVault.deploy(
    await policy.getAddress(),
    await tokenA.getAddress(),
    await tokenB.getAddress(),
    await lpToken.getAddress()
  );

  const AMMPool = await ethers.getContractFactory("AMMPool");
  const pool: any = await AMMPool.deploy(
    await policy.getAddress(),
    await tokenA.getAddress(),
    await tokenB.getAddress(),
    await lpToken.getAddress(),
    await vault.getAddress()
  );

  const contracts = {
    tokenA: await tokenA.getAddress(),
    tokenB: await tokenB.getAddress(),
    lpToken: await lpToken.getAddress(),
    policy: await policy.getAddress(),
    pool: await pool.getAddress(),
    vault: await vault.getAddress()
  };

  await lpToken.setPool(contracts.pool);
  await vault.setPool(contracts.pool);

  await policy.setTokenApproval(contracts.tokenA, true);
  await policy.setTokenApproval(contracts.tokenB, true);
  await policy.setTraderPolicy(
    traderWallet.address,
    true,
    CONFIG.traderMaxSwapAmount,
    CONFIG.traderSpendingLimit,
    CONFIG.policyWindowDuration
  );
  await policy.setLPPolicy(
    lpWallet.address,
    true,
    CONFIG.lpMaxLiquidityAdd,
    CONFIG.lpMaxLiquidityRemove,
    CONFIG.lpMaxFeeWithdrawal,
    CONFIG.policyWindowDuration
  );
  await policy.setRecorder(contracts.pool, true);
  await policy.setRecorder(contracts.vault, true);

  await tokenA.transfer(lpWallet.address, CONFIG.initialLpTokenA);
  await tokenB.transfer(lpWallet.address, CONFIG.initialLpTokenB);
  await tokenA.transfer(traderWallet.address, CONFIG.initialTraderTokenA);
  await tokenB.transfer(traderWallet.address, CONFIG.initialTraderTokenB);

  await tokenA.connect(lpWallet).approve(contracts.pool, ethers.MaxUint256);
  await tokenB.connect(lpWallet).approve(contracts.pool, ethers.MaxUint256);
  await tokenA.connect(traderWallet).approve(contracts.pool, ethers.MaxUint256);
  await tokenB.connect(traderWallet).approve(contracts.pool, ethers.MaxUint256);

  return {
    network: network.name,
    contracts,
    actors: {
      deployer: deployer.address,
      lp: lpWallet.address,
      trader: traderWallet.address
    },
    config: CONFIG,
    instances: {
      tokenA,
      tokenB,
      lpToken,
      policy,
      pool,
      vault
    }
  };
}

export const deployLocalContracts = deployContracts;

async function main() {
  const deployment = await deployContracts();
  const { instances: _instances, ...jsonDeployment } = deployment;

  console.log(stringifyDeployment(jsonDeployment));
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
