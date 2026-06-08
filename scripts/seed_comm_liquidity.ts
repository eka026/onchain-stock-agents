import { ethers } from "hardhat";
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
};

type Scenario = {
  tokens: TokenConfig[];
  pools: PoolConfig[];
};

const TARGET_POOL_ID = process.env.POOL_ID ?? "COMM-USD";
const DEFAULT_AMOUNT = ethers.parseEther("1000");
const MIN_SAFE_RESERVE = ethers.parseEther("1");

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function loadJson<T>(filePath: string): T {
  const resolved = path.isAbsolute(filePath) ? filePath : path.join(__dirname, "..", filePath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`Missing file: ${resolved}`);
  }
  return JSON.parse(fs.readFileSync(resolved, "utf8")) as T;
}

function firstPrivateKey(name: string): string {
  return requireEnv(name)
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)[0];
}

function tokenMap(scenario: Scenario): Map<string, TokenConfig> {
  return new Map(scenario.tokens.map((token) => [token.symbol, token]));
}

async function waitForReceipt(label: string, txPromise: Promise<any>) {
  const tx = await txPromise;
  console.log(`Submitted ${label}: ${tx.hash}`);
  const receipt = await tx.wait();
  console.log(`Confirmed ${label}: tx=${tx.hash} status=${receipt?.status} block=${receipt?.blockNumber}`);
  return receipt;
}

async function fundIfNeeded(token: any, deployer: any, recipient: string, symbol: string, required: bigint) {
  const balance = await token.balanceOf(recipient);
  if (balance >= required) {
    console.log(`Skip funding ${symbol}: lpBalance=${balance.toString()} required=${required.toString()}`);
    return;
  }

  const amount = required - balance;
  const deployerBalance = await token.balanceOf(deployer.address);
  if (deployerBalance < amount) {
    throw new Error(
      `Deployer has insufficient ${symbol}: deployerBalance=${deployerBalance.toString()} needed=${amount.toString()}`
    );
  }

  await waitForReceipt(`fund ${symbol}->${recipient}`, token.connect(deployer).transfer(recipient, amount));
}

async function approveIfNeeded(token: any, owner: string, spender: string, symbol: string, required: bigint) {
  const allowance = await token.allowance(owner, spender);
  if (allowance >= required) {
    console.log(`Skip approve ${symbol}: allowance=${allowance.toString()}`);
    return;
  }

  await waitForReceipt(`approve ${symbol}->${spender}`, token.approve(spender, ethers.MaxUint256));
}

async function main() {
  process.env.RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? requireEnv("RPC_URL");
  requireEnv("DEPLOYER_PRIVATE_KEY");

  const [deployer] = await ethers.getSigners();
  const lp = new ethers.Wallet(firstPrivateKey("LP_PRIVATE_KEYS"), ethers.provider);

  const scenarioPath = process.env.SCENARIO_PATH ?? "data/scenarios/sepolia.json";
  const scenario = loadJson<Scenario>(scenarioPath);
  const poolConfig = scenario.pools.find((pool) => pool.id === TARGET_POOL_ID);
  if (!poolConfig) {
    throw new Error(`Pool not found in ${scenarioPath}: ${TARGET_POOL_ID}`);
  }

  const tokens = tokenMap(scenario);
  const baseConfig = tokens.get(poolConfig.base_symbol);
  const quoteConfig = tokens.get(poolConfig.quote_symbol);
  if (!baseConfig || !quoteConfig) {
    throw new Error(`Pool ${poolConfig.id} references missing token config`);
  }

  const tokenAbi = loadJson<unknown[]>("agents/abis/MockERC20.json");
  const poolAbi = loadJson<unknown[]>("agents/abis/AMMPool.json");
  const baseTokenForDeployer = new ethers.Contract(baseConfig.address, tokenAbi, deployer);
  const quoteTokenForDeployer = new ethers.Contract(quoteConfig.address, tokenAbi, deployer);
  const baseToken = new ethers.Contract(baseConfig.address, tokenAbi, lp);
  const quoteToken = new ethers.Contract(quoteConfig.address, tokenAbi, lp);
  const pool = new ethers.Contract(poolConfig.pool_address, poolAbi, lp);

  const amountA = process.env.LIQUIDITY_AMOUNT_A
    ? ethers.parseEther(process.env.LIQUIDITY_AMOUNT_A)
    : DEFAULT_AMOUNT;
  const amountB = process.env.LIQUIDITY_AMOUNT_B
    ? ethers.parseEther(process.env.LIQUIDITY_AMOUNT_B)
    : DEFAULT_AMOUNT;

  const reserveA = await pool.reserveA();
  const reserveB = await pool.reserveB();
  console.log(`Scenario: ${scenarioPath}`);
  console.log(`LP: ${lp.address}`);
  console.log(`${poolConfig.id}: pool=${poolConfig.pool_address}`);
  console.log(`Current reserves: ${poolConfig.base_symbol}=${reserveA.toString()} ${poolConfig.quote_symbol}=${reserveB.toString()}`);

  if (reserveA >= MIN_SAFE_RESERVE && reserveB >= MIN_SAFE_RESERVE) {
    console.log(`Skip addLiquidity: ${poolConfig.id} already has safe reserves`);
    return;
  }

  await fundIfNeeded(baseTokenForDeployer, deployer, lp.address, poolConfig.base_symbol, amountA);
  await fundIfNeeded(quoteTokenForDeployer, deployer, lp.address, poolConfig.quote_symbol, amountB);
  await approveIfNeeded(baseToken, lp.address, poolConfig.pool_address, poolConfig.base_symbol, amountA);
  await approveIfNeeded(quoteToken, lp.address, poolConfig.pool_address, poolConfig.quote_symbol, amountB);

  await waitForReceipt(
    `addLiquidity ${poolConfig.id} amountA=${amountA.toString()} amountB=${amountB.toString()}`,
    pool.addLiquidity(amountA, amountB, 0)
  );

  const finalReserveA = await pool.reserveA();
  const finalReserveB = await pool.reserveB();
  console.log(`Final reserves: ${poolConfig.base_symbol}=${finalReserveA.toString()} ${poolConfig.quote_symbol}=${finalReserveB.toString()}`);
}

function describeError(error: unknown): string {
  if (error instanceof Error) {
    const details: Record<string, unknown> = { name: error.name, message: error.message };
    for (const key of ["code", "reason", "shortMessage", "method", "transaction", "data"]) {
      const value = (error as any)[key];
      if (value !== undefined) {
        details[key] = value;
      }
    }
    return JSON.stringify(details, (_key, value) => (typeof value === "bigint" ? value.toString() : value));
  }
  return String(error);
}

main().catch((error) => {
  console.error(describeError(error));
  process.exitCode = 1;
});
