import { ethers } from "hardhat";
import fs from "fs";
import path from "path";

const POLICY_ADDRESS = "0xA29D3C234170f63B0809BeD7efD8a6b36b7f540f";
const TRADERS = [
  "0xc11547A4DcbB6ff8F60B8AdD279070491Ba306f9",
  "0x39bf768AD2b7fb00b30875a631E6F84079756A2C",
  "0x5fcD93Ac8edfeE4cB4348C1736552941DfC20006",
];

const POLICY = {
  enabled: true,
  maxSwapAmount: ethers.parseEther("1000"),
  spendingLimit: ethers.parseEther("100000"),
  resetPeriod: 3_600n,
};

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function requireRpcUrl(): string {
  return process.env.RPC_URL ?? process.env.SEPOLIA_RPC_URL ?? requireEnv("RPC_URL");
}

function loadAgentPolicyAbi(): unknown[] {
  const abiPath = path.join(__dirname, "..", "agents", "abis", "AgentPolicy.json");
  if (!fs.existsSync(abiPath)) {
    throw new Error(`Missing AgentPolicy ABI: ${abiPath}`);
  }
  return JSON.parse(fs.readFileSync(abiPath, "utf8"));
}

async function main() {
  requireRpcUrl();
  requireEnv("DEPLOYER_PRIVATE_KEY");

  const [deployer] = await ethers.getSigners();
  const abi = loadAgentPolicyAbi();
  const policy = new ethers.Contract(POLICY_ADDRESS, abi, deployer);

  console.log(`Using deployer: ${deployer.address}`);
  console.log(`AgentPolicy: ${POLICY_ADDRESS}`);

  for (const trader of TRADERS) {
    try {
      const before = await policy.traderPolicies(trader);
      console.log(
        `Before ${trader}: enabled=${before[0]} maxSwapAmount=${before[1].toString()} spendingLimit=${before[2].toString()} resetPeriod=${before[5].toString()}`
      );

      const tx = await policy.setTraderPolicy(
        trader,
        POLICY.enabled,
        POLICY.maxSwapAmount,
        POLICY.spendingLimit,
        POLICY.resetPeriod
      );
      console.log(`Submitted ${trader}: ${tx.hash}`);

      const receipt = await tx.wait();
      console.log(`Confirmed ${trader}: tx=${tx.hash} status=${receipt?.status} block=${receipt?.blockNumber}`);

      const after = await policy.traderPolicies(trader);
      console.log(
        `After ${trader}: enabled=${after[0]} maxSwapAmount=${after[1].toString()} spendingLimit=${after[2].toString()} resetPeriod=${after[5].toString()}`
      );
    } catch (error) {
      const message = describeError(error);
      throw new Error(`Failed to enable trader ${trader}: ${message}`);
    }
  }
}

function describeError(error: unknown): string {
  if (error instanceof Error) {
    const details: Record<string, unknown> = {
      name: error.name,
      message: error.message,
    };
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
