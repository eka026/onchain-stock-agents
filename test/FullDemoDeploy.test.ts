import { expect } from "chai";
import { ethers } from "hardhat";
import fs from "fs";
import os from "os";
import path from "path";
import { deployContracts } from "../scripts/deploy";

describe("Full demo deployment", function () {
  it("deploys every scenario market, seeds liquidity, configures actors, and writes a runtime scenario", async function () {
    const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), "onchain-stock-agents-"));
    const outputScenarioPath = path.join(outputDir, "sepolia.json");

    const deployment = await deployContracts({
      templateScenarioPath: "data/scenarios/demo.json",
      outputScenarioPath,
    });

    const writtenScenario = JSON.parse(fs.readFileSync(outputScenarioPath, "utf8"));

    expect(writtenScenario.policy_address).to.equal(deployment.contracts.policy);
    expect(writtenScenario.tokens).to.have.length(11);
    expect(writtenScenario.pools).to.have.length(10);
    expect(writtenScenario.tokens.every((token: any) => !isPlaceholder(token.address))).to.equal(true);
    expect(writtenScenario.pools.every((pool: any) => !isPlaceholder(pool.pool_address))).to.equal(true);
    expect(writtenScenario.pools.every((pool: any) => !isPlaceholder(pool.lp_token_address))).to.equal(true);
    expect(writtenScenario.pools.every((pool: any) => !isPlaceholder(pool.vault_address))).to.equal(true);

    expect(deployment.actors.traders).to.have.length(2);
    expect(deployment.actors.lps).to.have.length(1);

    const firstTrader = deployment.actors.traders[0];
    const firstLp = deployment.actors.lps[0];
    const traderPolicy = await deployment.instances.policy.traderPolicies(firstTrader);
    const lpPolicy = await deployment.instances.policy.lpPolicies(firstLp);
    expect(traderPolicy.enabled).to.equal(true);
    expect(lpPolicy.enabled).to.equal(true);

    for (const token of writtenScenario.tokens) {
      expect(await deployment.instances.policy.isTokenApproved(token.address)).to.equal(true);
    }

    for (const pool of writtenScenario.pools) {
      const poolInstance = deployment.instances.pools[pool.id].pool;
      const baseToken = deployment.instances.tokens[pool.base_symbol];
      const quoteToken = deployment.instances.tokens[pool.quote_symbol];

      expect(await poolInstance.reserveA()).to.be.gt(0n);
      expect(await poolInstance.reserveB()).to.be.gt(0n);
      expect(await poolInstance.spotPrice()).to.be.gt(0n);
      expect(await deployment.instances.policy.isRecorder(pool.pool_address)).to.equal(true);
      expect(await deployment.instances.policy.isRecorder(pool.vault_address)).to.equal(true);
      expect(await baseToken.allowance(firstTrader, pool.pool_address)).to.equal(ethers.MaxUint256);
      expect(await quoteToken.allowance(firstLp, pool.pool_address)).to.equal(ethers.MaxUint256);
    }
  });
});

function isPlaceholder(address: string) {
  return address.toLowerCase().startsWith("0x0000000000000000000000000000000000000");
}
