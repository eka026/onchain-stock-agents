import { ethers } from "hardhat";
import fs from "fs";
import path from "path";

type TokenConfig = {
  symbol: string;
  address: string;
};

type PoolConfig = {
  base_symbol: string;
  quote_symbol: string;
};

type Scenario = {
  tokens: TokenConfig[];
  pools: PoolConfig[];
};

const TARGET_TRADERS = [
  "0xc11547A4DcbB6ff8F60B8AdD279070491Ba306f9",
  "0x39bf768AD2b7fb00b30875a631E6F84079756A2C",
  "0x5fcD93Ac8edfeE4cB4348C1736552941DfC20006",
];

const INITIAL_TRADER_BASE_BALANCE_PER_POOL = ethers.parseEther("1000");
const INITIAL_TRADER_QUOTE_BALANCE_PER_POOL = ethers.parseEther("1000");

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

function requiredBalances(scenario: Scenario): Map<string, bigint> {
  const usage = new Map<string, { base: bigint; quote: bigint }>();
  for (const pool of scenario.pools) {
    usage.set(pool.base_symbol, usage.get(pool.base_symbol) ?? { base: 0n, quote: 0n });
    usage.set(pool.quote_symbol, usage.get(pool.quote_symbol) ?? { base: 0n, quote: 0n });
    usage.get(pool.base_symbol)!.base += 1n;
    usage.get(pool.quote_symbol)!.quote += 1n;
  }

  const result = new Map<string, bigint>();
  for (const token of scenario.tokens) {
    const tokenUsage = usage.get(token.symbol) ?? { base: 0n, quote: 0n };
    result.set(
      token.symbol,
      INITIAL_TRADER_BASE_BALANCE_PER_POOL * tokenUsage.base +
        INITIAL_TRADER_QUOTE_BALANCE_PER_POOL * tokenUsage.quote
    );
  }
  return result;
}

async function main() {
  process.env.RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? requireEnv("RPC_URL");
  requireEnv("DEPLOYER_PRIVATE_KEY");

  const [deployer] = await ethers.getSigners();
  const scenarioPath = process.env.SCENARIO_PATH ?? "data/scenarios/sepolia.json";
  const scenario = loadJson<Scenario>(scenarioPath);
  const tokenAbi = loadJson<unknown[]>("agents/abis/MockERC20.json");
  const targets = requiredBalances(scenario);

  console.log(`Using deployer: ${deployer.address}`);
  console.log(`Scenario: ${scenarioPath}`);

  for (const tokenConfig of scenario.tokens) {
    const token = new ethers.Contract(tokenConfig.address, tokenAbi, deployer);
    const targetBalance = targets.get(tokenConfig.symbol) ?? 0n;
    if (targetBalance <= 0n) {
      continue;
    }

    const deployerBalance = await token.balanceOf(deployer.address);
    console.log(`${tokenConfig.symbol}: target per trader=${targetBalance.toString()} deployerBalance=${deployerBalance.toString()}`);

    for (const trader of TARGET_TRADERS) {
      const balance = await token.balanceOf(trader);
      if (balance >= targetBalance) {
        console.log(`Skip ${tokenConfig.symbol}->${trader}: balance=${balance.toString()}`);
        continue;
      }

      const amount = targetBalance - balance;
      console.log(`Transfer ${tokenConfig.symbol}->${trader}: current=${balance.toString()} amount=${amount.toString()}`);
      const tx = await token.transfer(trader, amount);
      console.log(`Submitted ${tokenConfig.symbol}->${trader}: ${tx.hash}`);
      const receipt = await tx.wait();
      console.log(`Confirmed ${tokenConfig.symbol}->${trader}: tx=${tx.hash} status=${receipt?.status} block=${receipt?.blockNumber}`);
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
