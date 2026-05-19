import { artifacts } from "hardhat";
import fs from "fs";
import path from "path";

const CONTRACTS = ["AgentPolicy", "StockToken", "Exchange", "DividendVault"];

async function main() {
  const outDir = path.join(__dirname, "../agents/abis");
  fs.mkdirSync(outDir, { recursive: true });

  for (const name of CONTRACTS) {
    const artifact = await artifacts.readArtifact(name);
    const outPath = path.join(outDir, `${name}.json`);
    fs.writeFileSync(outPath, JSON.stringify(artifact.abi, null, 2));
    console.log(`  ${name} → agents/abis/${name}.json`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
