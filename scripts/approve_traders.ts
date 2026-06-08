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

const TARGET_TRADERS = new Set([
  "0xc11547a4dcbb6ff8f60b8add279070491ba306f9",
  "0x39bf768ad2b7fb00b30875a631e6f84079756a2c",
  "0x5fcd93ac8edfee4cb4348c1736552941dfc20006",
]);

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function privateKeys(name: string): string[] {
  return requireEnv(name)
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function loadJson<T>(filePath: string): T {
  const resolved = path.isAbsolute(filePath) ? filePath : path.join(__dirname, "..", filePath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`Missing file: ${resolved}`);
  }
  return JSON.parse(fs.readFileSync(resolved, "utf8")) as T;
}

function tokenBySymbol(scenario: Scenario): Map<string, TokenConfig> {
  return new Map(scenario.tokens.map((token) => [token.symbol, token]));
}

async function main() {
  process.env.RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? requireEnv("RPC_URL");

  const scenarioPath = process.env.SCENARIO_PATH ?? "data/scenarios/sepolia.json";
  const scenario = loadJson<Scenario>(scenarioPath);
  const tokenMap = tokenBySymbol(scenario);
  const tokenAbi = loadJson<unknown[]>("agents/abis/MockERC20.json");

  const wallets = privateKeys("TRADER_PRIVATE_KEYS")
    .map((key) => new ethers.Wallet(key, ethers.provider))
    .filter((wallet) => TARGET_TRADERS.has(wallet.address.toLowerCase()));

  if (wallets.length !== TARGET_TRADERS.size) {
    const found = new Set(wallets.map((wallet) => wallet.address.toLowerCase()));
    const missing = [...TARGET_TRADERS].filter((address) => !found.has(address));
    throw new Error(`Missing private keys for target traders: ${missing.join(", ")}`);
  }

  console.log(`Scenario: ${scenarioPath}`);
  console.log(`Approving ${wallets.length} target traders across ${scenario.pools.length} pools`);

  for (const wallet of wallets) {
    const ethBalance = await ethers.provider.getBalance(wallet.address);
    console.log(`Trader ${wallet.address} ETH balance=${ethers.formatEther(ethBalance)}`);

    for (const pool of scenario.pools) {
      for (const symbol of [pool.base_symbol, pool.quote_symbol]) {
        const tokenConfig = tokenMap.get(symbol);
        if (!tokenConfig) {
          throw new Error(`Pool ${pool.id} references unknown token symbol: ${symbol}`);
        }

        const token = new ethers.Contract(tokenConfig.address, tokenAbi, wallet);
        const allowance = await token.allowance(wallet.address, pool.pool_address);
        const balance = await token.balanceOf(wallet.address);

        if (allowance === ethers.MaxUint256) {
          console.log(`Skip ${wallet.address} ${symbol}->${pool.id}: allowance already MaxUint256 balance=${balance.toString()}`);
          continue;
        }

        console.log(
          `Approve ${wallet.address} ${symbol}->${pool.id}: currentAllowance=${allowance.toString()} balance=${balance.toString()}`
        );
        const tx = await token.approve(pool.pool_address, ethers.MaxUint256);
        console.log(`Submitted ${wallet.address} ${symbol}->${pool.id}: ${tx.hash}`);
        const receipt = await tx.wait();
        console.log(`Confirmed ${wallet.address} ${symbol}->${pool.id}: tx=${tx.hash} status=${receipt?.status} block=${receipt?.blockNumber}`);
      }
    }
  }
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
