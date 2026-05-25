import { ethers, network } from "hardhat";

function requireEnv(key: string) {
  const value = process.env[key];
  if (!value) {
    throw new Error(`Missing required env var: ${key}`);
  }
  return value;
}

function privateKeys(key: string) {
  return requireEnv(key)
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

async function printWalletBalance(role: string, privateKey: string) {
  const wallet = new ethers.Wallet(privateKey, ethers.provider);
  const balance = await ethers.provider.getBalance(wallet.address);
  console.log(`${role}: ${wallet.address} balance=${ethers.formatEther(balance)} ETH`);
  if (balance === 0n) {
    throw new Error(`${role} has zero Sepolia ETH`);
  }
}

async function main() {
  const chainId = BigInt(network.config.chainId ?? 0);
  const liveChainId = (await ethers.provider.getNetwork()).chainId;
  console.log(`network=${network.name} chainId=${liveChainId}`);
  if (network.name !== "sepolia" || liveChainId !== 11155111n || (chainId !== 0n && chainId !== 11155111n)) {
    throw new Error("Hardhat is not connected to Sepolia");
  }

  await printWalletBalance("deployer", requireEnv("DEPLOYER_PRIVATE_KEY"));
  for (const [index, key] of privateKeys("TRADER_PRIVATE_KEYS").entries()) {
    await printWalletBalance(`trader ${index + 1}`, key);
  }
  for (const [index, key] of privateKeys("LP_PRIVATE_KEYS").entries()) {
    await printWalletBalance(`lp ${index + 1}`, key);
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
