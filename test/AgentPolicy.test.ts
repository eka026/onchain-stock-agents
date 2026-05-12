import { expect } from "chai";
import { ethers, network } from "hardhat";

describe("AgentPolicy", function () {
  async function deployPolicy() {
    const [owner, trader, firm, token, recorder, outsider] = await ethers.getSigners();
    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    const policy = await AgentPolicy.deploy();

    return { policy, owner, trader, firm, token, recorder, outsider };
  }

  async function increaseTime(seconds: number) {
    await network.provider.send("evm_increaseTime", [seconds]);
    await network.provider.send("evm_mine");
  }

  it("stores token policy and rejects unapproved or paused assets", async function () {
    const { policy, token, trader } = await deployPolicy();

    await policy.setTraderPolicy(trader.address, true, 100, 1_000, 60);
    await policy.setTokenPolicy(token.address, true, 50, false);

    expect(await policy.isTokenApproved(token.address)).to.equal(true);
    expect(await policy.tokenMaxTradeSize(token.address)).to.equal(50);
    expect(await policy.isTokenTradingPaused(token.address)).to.equal(false);
    await expect(policy.validateTrade(trader.address, token.address, 50, 1_000)).to.not.be.reverted;

    await policy.setTokenPolicy(token.address, true, 50, true);
    await expect(policy.validateTrade(trader.address, token.address, 1, 1)).to.be.revertedWith(
      "POLICY_TOKEN_PAUSED"
    );
  });

  it("rejects disabled traders, oversized trader trades, and oversized token trades", async function () {
    const { policy, token, trader } = await deployPolicy();

    await policy.setTokenPolicy(token.address, true, 25, false);
    await expect(policy.validateTrade(trader.address, token.address, 1, 1)).to.be.revertedWith(
      "POLICY_TRADER_DISABLED"
    );

    await policy.setTraderPolicy(trader.address, true, 10, 1_000, 60);
    await expect(policy.validateTrade(trader.address, token.address, 11, 1)).to.be.revertedWith(
      "POLICY_TRADE_TOO_LARGE"
    );
    await policy.setTraderPolicy(trader.address, true, 100, 1_000, 60);
    await expect(policy.validateTrade(trader.address, token.address, 26, 1)).to.be.revertedWith(
      "POLICY_TOKEN_TRADE_TOO_LARGE"
    );
  });

  it("tracks trader spending within a rolling window", async function () {
    const { policy, token, trader, recorder } = await deployPolicy();

    await policy.setTokenPolicy(token.address, true, 100, false);
    await policy.setTraderPolicy(trader.address, true, 100, 1_000, 60);
    await policy.setRecorder(recorder.address, true);

    await policy.connect(recorder).recordSpending(trader.address, 600);
    expect(await policy.currentSpentAmount(trader.address)).to.equal(600);
    await expect(policy.validateTrade(trader.address, token.address, 1, 401)).to.be.revertedWith(
      "POLICY_SPENDING_LIMIT"
    );

    await increaseTime(61);
    expect(await policy.currentSpentAmount(trader.address)).to.equal(0);
    await expect(policy.validateTrade(trader.address, token.address, 1, 1_000)).to.not.be.reverted;
  });

  it("allows only approved recorders to record spending and dividends", async function () {
    const { policy, trader, firm, recorder, outsider } = await deployPolicy();

    await policy.setTraderPolicy(trader.address, true, 100, 1_000, 60);
    await policy.setDividendPolicy(firm.address, true, 1_000, 60);

    await expect(policy.connect(outsider).recordSpending(trader.address, 1)).to.be.revertedWith(
      "POLICY_NOT_RECORDER"
    );
    await expect(policy.connect(outsider).recordDividend(firm.address, 1)).to.be.revertedWith(
      "POLICY_NOT_RECORDER"
    );

    await policy.setRecorder(recorder.address, true);
    await expect(policy.connect(recorder).recordSpending(trader.address, 1)).to.not.be.reverted;
    await expect(policy.connect(recorder).recordDividend(firm.address, 1)).to.not.be.reverted;
  });

  it("validates dividend budgets within a rolling window", async function () {
    const { policy, firm, recorder } = await deployPolicy();

    await policy.setDividendPolicy(firm.address, true, 1_000, 60);
    await policy.setRecorder(recorder.address, true);

    await policy.connect(recorder).recordDividend(firm.address, 700);
    expect(await policy.currentDividendPaid(firm.address)).to.equal(700);
    await expect(policy.validateDividend(firm.address, 301)).to.be.revertedWith(
      "POLICY_DIVIDEND_BUDGET"
    );

    await increaseTime(61);
    expect(await policy.currentDividendPaid(firm.address)).to.equal(0);
    await expect(policy.validateDividend(firm.address, 1_000)).to.not.be.reverted;
  });

  it("restricts configuration to the owner", async function () {
    const { policy, token, trader, firm, recorder, outsider } = await deployPolicy();

    await expect(
      policy.connect(outsider).setTokenPolicy(token.address, true, 1, false)
    ).to.be.revertedWithCustomError(policy, "OwnableUnauthorizedAccount");
    await expect(
      policy.connect(outsider).setTraderPolicy(trader.address, true, 1, 1, 60)
    ).to.be.revertedWithCustomError(policy, "OwnableUnauthorizedAccount");
    await expect(
      policy.connect(outsider).setDividendPolicy(firm.address, true, 1, 60)
    ).to.be.revertedWithCustomError(policy, "OwnableUnauthorizedAccount");
    await expect(policy.connect(outsider).setRecorder(recorder.address, true)).to.be.revertedWithCustomError(
      policy,
      "OwnableUnauthorizedAccount"
    );
  });
});
