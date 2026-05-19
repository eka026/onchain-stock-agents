import { expect } from "chai";

import { deployLocalContracts } from "../scripts/deploy";

describe("deployLocalContracts", function () {
  it("deploys and configures the local market contracts", async function () {
    const deployment = await deployLocalContracts();

    expect(deployment.contracts.paymentToken).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.contracts.stockToken).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.contracts.policy).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.contracts.exchange).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.contracts.dividendVault).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.actors.deployer).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.actors.firm).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.actors.sellerAgent).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(deployment.actors.buyerAgent).to.match(/^0x[a-fA-F0-9]{40}$/);

    expect(await deployment.instances.policy.isTokenApproved(deployment.contracts.stockToken)).to.equal(true);
    expect(await deployment.instances.policy.tokenMaxTradeSize(deployment.contracts.stockToken)).to.equal(
      deployment.config.stockTokenMaxTradeSize
    );
    expect(await deployment.instances.policy.isTokenTradingPaused(deployment.contracts.stockToken)).to.equal(
      false
    );
    expect(await deployment.instances.policy.isRecorder(deployment.contracts.exchange)).to.equal(true);
    expect(await deployment.instances.policy.isRecorder(deployment.contracts.dividendVault)).to.equal(true);

    const sellerPolicy = await deployment.instances.policy.traderPolicies(deployment.actors.sellerAgent);
    expect(sellerPolicy.enabled).to.equal(true);
    expect(sellerPolicy.maxTradeSize).to.equal(deployment.config.agentMaxTradeSize);
    expect(sellerPolicy.spendingLimit).to.equal(deployment.config.agentSpendingLimit);

    const buyerPolicy = await deployment.instances.policy.traderPolicies(deployment.actors.buyerAgent);
    expect(buyerPolicy.enabled).to.equal(true);
    expect(buyerPolicy.maxTradeSize).to.equal(deployment.config.agentMaxTradeSize);
    expect(buyerPolicy.spendingLimit).to.equal(deployment.config.agentSpendingLimit);

    const firmDividendPolicy = await deployment.instances.policy.dividendPolicies(deployment.actors.firm);
    expect(firmDividendPolicy.enabled).to.equal(true);
    expect(firmDividendPolicy.budget).to.equal(deployment.config.firmDividendBudget);
  });
});
