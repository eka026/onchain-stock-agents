import { ethers, network } from "hardhat";
import fs from "fs";
import path from "path";

type TokenConfig = {
  symbol: string;
  address: string;
};

type PoolConfig = {
  id: string;
  base_symbol: string;
  quote_symbol: string;
  pool_address: string;
  lp_token_address: string;
  vault_address: string;
};

type ScenarioTemplate = {
  seed: number;
  news_file: string;
  policy_address: string;
  min_interval_ticks: number;
  max_interval_ticks: number;
  max_events: number;
  broadcast_to_all_traders: boolean;
  tokens: TokenConfig[];
  pools: PoolConfig[];
};

type DeployOptions = {
  templateScenarioPath?: string;
  outputScenarioPath?: string;
};

const CONFIG = {
  tokenInitialSupply: ethers.parseEther("1000000"),
  initialLpBaseBalancePerPool: ethers.parseEther("10000"),
  initialLpQuoteBalancePerPool: ethers.parseEther("10000"),
  initialTraderBaseBalancePerPool: ethers.parseEther("1000"),
  initialTraderQuoteBalancePerPool: ethers.parseEther("1000"),
  initialPoolBaseLiquidity: ethers.parseEther("1000"),
  initialPoolQuoteLiquidity: ethers.parseEther("1000"),
  traderMaxSwapAmount: ethers.parseEther("1000"),
  traderSpendingLimit: ethers.parseEther("100000"),
  lpMaxLiquidityAdd: ethers.parseEther("100000"),
  lpMaxLiquidityRemove: ethers.parseEther("100000"),
  lpMaxFeeWithdrawal: ethers.parseEther("100000"),
  policyWindowDuration: 3_600n,
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

function getPrivateKeys(key: string) {
  return requireEnv(key)
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function resolveProjectPath(filePath: string) {
  return path.isAbsolute(filePath) ? filePath : path.join(__dirname, "..", filePath);
}

function defaultOutputScenarioPath() {
  const networkName = network.name === "hardhat" || network.name === "localhost" ? "local" : network.name;
  return path.join("data", "scenarios", `${networkName}.json`);
}

function loadScenarioTemplate(templateScenarioPath: string): ScenarioTemplate {
  const resolvedPath = resolveProjectPath(templateScenarioPath);
  const scenario = JSON.parse(fs.readFileSync(resolvedPath, "utf8")) as ScenarioTemplate;
  if (!Array.isArray(scenario.tokens) || scenario.tokens.length === 0) {
    throw new Error(`Scenario template has no tokens: ${templateScenarioPath}`);
  }
  if (!Array.isArray(scenario.pools) || scenario.pools.length === 0) {
    throw new Error(`Scenario template has no pools: ${templateScenarioPath}`);
  }
  return scenario;
}

async function deployContract(name: string, args: unknown[] = []) {
  const Factory = await ethers.getContractFactory(name);
  const contract: any = await Factory.deploy(...args);
  await contract.waitForDeployment();
  return contract;
}

async function waitForTransaction(txPromise: Promise<any>) {
  const tx = await txPromise;
  await tx.wait();
  return tx;
}

async function resolveActors() {
  const signers = await ethers.getSigners();
  const deployer = signers[0];
  const isLocalNetwork = network.name === "hardhat" || network.name === "localhost";

  if (isLocalNetwork) {
    if (signers.length < 4) {
      throw new Error("Local full-demo deployment requires at least 4 Hardhat signers");
    }
    return {
      deployer,
      lps: [signers[1]],
      traders: [signers[2], signers[3]],
    };
  }

  const lpKeys = getPrivateKeys("LP_PRIVATE_KEYS");
  const traderKeys = getPrivateKeys("TRADER_PRIVATE_KEYS");
  if (lpKeys.length < 1) {
    throw new Error("Full-demo deployment requires at least one LP_PRIVATE_KEYS entry");
  }
  if (traderKeys.length < 2) {
    throw new Error("Full-demo deployment requires at least two TRADER_PRIVATE_KEYS entries");
  }

  return {
    deployer,
    lps: lpKeys.map((key) => new ethers.Wallet(key, ethers.provider)),
    traders: traderKeys.map((key) => new ethers.Wallet(key, ethers.provider)),
  };
}

function countPoolUsage(pools: PoolConfig[]) {
  const usage: Record<string, { base: number; quote: number }> = {};
  for (const pool of pools) {
    usage[pool.base_symbol] ??= { base: 0, quote: 0 };
    usage[pool.quote_symbol] ??= { base: 0, quote: 0 };
    usage[pool.base_symbol].base += 1;
    usage[pool.quote_symbol].quote += 1;
  }
  return usage;
}

function tokenName(symbol: string) {
  return symbol === "USD" ? "Demo USD" : `${symbol} Demo Token`;
}

async function transferIfPositive(token: any, recipient: string, amount: bigint) {
  if (amount > 0n) {
    await waitForTransaction(token.transfer(recipient, amount));
  }
}

async function approvePoolTokens(actor: any, tokenA: any, tokenB: any, poolAddress: string) {
  await waitForTransaction(tokenA.connect(actor).approve(poolAddress, ethers.MaxUint256));
  await waitForTransaction(tokenB.connect(actor).approve(poolAddress, ethers.MaxUint256));
}

function buildRuntimeScenario(
  template: ScenarioTemplate,
  policyAddress: string,
  tokenAddresses: Record<string, string>,
  poolAddresses: Record<string, { pool: string; lpToken: string; vault: string }>
): ScenarioTemplate {
  return {
    ...template,
    policy_address: policyAddress,
    tokens: template.tokens.map((token) => ({
      ...token,
      address: tokenAddresses[token.symbol],
    })),
    pools: template.pools.map((pool) => ({
      ...pool,
      pool_address: poolAddresses[pool.id].pool,
      lp_token_address: poolAddresses[pool.id].lpToken,
      vault_address: poolAddresses[pool.id].vault,
    })),
  };
}

function writeRuntimeScenario(outputScenarioPath: string, scenario: ScenarioTemplate) {
  const resolvedPath = resolveProjectPath(outputScenarioPath);
  fs.mkdirSync(path.dirname(resolvedPath), { recursive: true });
  fs.writeFileSync(resolvedPath, JSON.stringify(scenario, null, 2) + "\n");
  return outputScenarioPath;
}

export async function deployContracts(options: DeployOptions = {}) {
  const templateScenarioPath =
    options.templateScenarioPath ?? process.env.DEPLOY_SCENARIO_TEMPLATE ?? "data/scenarios/demo.json";
  const outputScenarioPath =
    options.outputScenarioPath ?? process.env.DEPLOY_OUTPUT_SCENARIO ?? defaultOutputScenarioPath();
  const scenario = loadScenarioTemplate(templateScenarioPath);
  const actors = await resolveActors();

  const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
  const policy: any = await AgentPolicy.deploy();
  await policy.waitForDeployment();
  const policyAddress = await policy.getAddress();

  const tokens: Record<string, any> = {};
  const tokenAddresses: Record<string, string> = {};
  for (const token of scenario.tokens) {
    const contract = await deployContract("MockERC20", [
      tokenName(token.symbol),
      token.symbol,
      CONFIG.tokenInitialSupply,
    ]);
    tokens[token.symbol] = contract;
    tokenAddresses[token.symbol] = await contract.getAddress();
    await waitForTransaction(policy.setTokenApproval(tokenAddresses[token.symbol], true));
  }

  const pools: Record<string, { lpToken: any; vault: any; pool: any }> = {};
  const poolAddresses: Record<string, { pool: string; lpToken: string; vault: string }> = {};
  for (const poolConfig of scenario.pools) {
    const baseToken = tokens[poolConfig.base_symbol];
    const quoteToken = tokens[poolConfig.quote_symbol];
    if (!baseToken || !quoteToken) {
      throw new Error(`Pool ${poolConfig.id} references an unknown token`);
    }

    const lpToken = await deployContract("LPToken", [`${poolConfig.id} LP`, `${poolConfig.id}-LP`]);
    const vault = await deployContract("FeeVault", [
      policyAddress,
      await baseToken.getAddress(),
      await quoteToken.getAddress(),
      await lpToken.getAddress(),
    ]);
    const pool = await deployContract("AMMPool", [
      policyAddress,
      await baseToken.getAddress(),
      await quoteToken.getAddress(),
      await lpToken.getAddress(),
      await vault.getAddress(),
    ]);

    const poolAddress = await pool.getAddress();
    const vaultAddress = await vault.getAddress();
    const lpTokenAddress = await lpToken.getAddress();

    await waitForTransaction(lpToken.setPool(poolAddress));
    await waitForTransaction(vault.setPool(poolAddress));
    await waitForTransaction(policy.setRecorder(poolAddress, true));
    await waitForTransaction(policy.setRecorder(vaultAddress, true));

    pools[poolConfig.id] = { lpToken, vault, pool };
    poolAddresses[poolConfig.id] = {
      pool: poolAddress,
      lpToken: lpTokenAddress,
      vault: vaultAddress,
    };
  }

  for (const trader of actors.traders) {
    await waitForTransaction(
      policy.setTraderPolicy(
        trader.address,
        true,
        CONFIG.traderMaxSwapAmount,
        CONFIG.traderSpendingLimit,
        CONFIG.policyWindowDuration
      )
    );
  }
  for (const lp of actors.lps) {
    await waitForTransaction(
      policy.setLPPolicy(
        lp.address,
        true,
        CONFIG.lpMaxLiquidityAdd,
        CONFIG.lpMaxLiquidityRemove,
        CONFIG.lpMaxFeeWithdrawal,
        CONFIG.policyWindowDuration
      )
    );
  }

  const usage = countPoolUsage(scenario.pools);
  for (const token of scenario.tokens) {
    const tokenUsage = usage[token.symbol] ?? { base: 0, quote: 0 };
    const lpAmount =
      CONFIG.initialLpBaseBalancePerPool * BigInt(tokenUsage.base) +
      CONFIG.initialLpQuoteBalancePerPool * BigInt(tokenUsage.quote);
    const traderAmount =
      CONFIG.initialTraderBaseBalancePerPool * BigInt(tokenUsage.base) +
      CONFIG.initialTraderQuoteBalancePerPool * BigInt(tokenUsage.quote);

    for (const lp of actors.lps) {
      await transferIfPositive(tokens[token.symbol], lp.address, lpAmount);
    }
    for (const trader of actors.traders) {
      await transferIfPositive(tokens[token.symbol], trader.address, traderAmount);
    }
  }

  for (const poolConfig of scenario.pools) {
    const poolAddress = poolAddresses[poolConfig.id].pool;
    const baseToken = tokens[poolConfig.base_symbol];
    const quoteToken = tokens[poolConfig.quote_symbol];
    for (const lp of actors.lps) {
      await approvePoolTokens(lp, baseToken, quoteToken, poolAddress);
    }
    for (const trader of actors.traders) {
      await approvePoolTokens(trader, baseToken, quoteToken, poolAddress);
    }
  }

  const seedLp = actors.lps[0];
  for (const poolConfig of scenario.pools) {
    await waitForTransaction(
      pools[poolConfig.id].pool
        .connect(seedLp)
        .addLiquidity(CONFIG.initialPoolBaseLiquidity, CONFIG.initialPoolQuoteLiquidity, 0)
    );
  }

  const runtimeScenario = buildRuntimeScenario(scenario, policyAddress, tokenAddresses, poolAddresses);
  const writtenScenarioPath = writeRuntimeScenario(outputScenarioPath, runtimeScenario);

  return {
    network: network.name,
    scenarioPath: writtenScenarioPath,
    contracts: {
      policy: policyAddress,
      tokens: tokenAddresses,
      pools: poolAddresses,
    },
    actors: {
      deployer: actors.deployer.address,
      lps: actors.lps.map((lp) => lp.address),
      traders: actors.traders.map((trader) => trader.address),
    },
    config: CONFIG,
    instances: {
      policy,
      tokens,
      pools,
    },
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
