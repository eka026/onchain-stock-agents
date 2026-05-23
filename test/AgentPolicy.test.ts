import { expect } from "chai";
import { ethers, network } from "hardhat";

describe("AgentPolicy", function () {
  async function deploy() {
    const [owner, trader, lp, token, recorder, outsider] = await ethers.getSigners();
    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    const policy = await AgentPolicy.deploy();
    return { policy, owner, trader, lp, token, recorder, outsider };
  }

  async function increaseTime(seconds: number) {
    await network.provider.send("evm_increaseTime", [seconds]);
    await network.provider.send("evm_mine");
  }

  // ── Token approval ────────────────────────────────────────────────────────

  it("approves and revokes token for swapping", async function () {
    const { policy, token } = await deploy();
    await policy.setTokenApproval(token.address, true);
    expect(await policy.isTokenApproved(token.address)).to.equal(true);
    await policy.setTokenApproval(token.address, false);
    expect(await policy.isTokenApproved(token.address)).to.equal(false);
  });

  // ── Trader policy / validateSwap ──────────────────────────────────────────

  it("rejects swap when token is not approved", async function () {
    const { policy, trader, token } = await deploy();
    await policy.setTraderPolicy(trader.address, true, 1_000, 50_000, 3_600);
    await expect(policy.validateSwap(trader.address, token.address, 100))
      .to.be.revertedWith("POLICY_TOKEN_NOT_APPROVED");
  });

  it("rejects swap when trader is disabled", async function () {
    const { policy, trader, token } = await deploy();
    await policy.setTokenApproval(token.address, true);
    await policy.setTraderPolicy(trader.address, false, 1_000, 50_000, 3_600);
    await expect(policy.validateSwap(trader.address, token.address, 100))
      .to.be.revertedWith("POLICY_TRADER_DISABLED");
  });

  it("rejects swap exceeding maxSwapAmount", async function () {
    const { policy, trader, token } = await deploy();
    await policy.setTokenApproval(token.address, true);
    await policy.setTraderPolicy(trader.address, true, 500, 50_000, 3_600);
    await expect(policy.validateSwap(trader.address, token.address, 501))
      .to.be.revertedWith("POLICY_SWAP_TOO_LARGE");
  });

  it("rejects swap when cumulative spending exceeds limit", async function () {
    const { policy, trader, token, recorder } = await deploy();
    await policy.setTokenApproval(token.address, true);
    await policy.setTraderPolicy(trader.address, true, 1_000, 1_000, 3_600);
    await policy.setRecorder(recorder.address, true);
    await policy.connect(recorder).recordSpending(trader.address, 800);
    await expect(policy.validateSwap(trader.address, token.address, 201))
      .to.be.revertedWith("POLICY_SPENDING_LIMIT");
  });

  it("resets spending after window expiry", async function () {
    const { policy, trader, token, recorder } = await deploy();
    await policy.setTokenApproval(token.address, true);
    await policy.setTraderPolicy(trader.address, true, 1_000, 1_000, 60);
    await policy.setRecorder(recorder.address, true);
    await policy.connect(recorder).recordSpending(trader.address, 800);
    await increaseTime(61);
    expect(await policy.currentSpentAmount(trader.address)).to.equal(0);
    await expect(policy.validateSwap(trader.address, token.address, 1_000)).to.not.be.reverted;
  });

  // ── LP policy ─────────────────────────────────────────────────────────────

  it("rejects addLiquidity when LP is disabled", async function () {
    const { policy, lp } = await deploy();
    await policy.setLPPolicy(lp.address, false, 10_000, 5_000, 500, 3_600);
    await expect(policy.validateLiquidityAdd(lp.address, 100, 100))
      .to.be.revertedWith("POLICY_LP_DISABLED");
  });

  it("rejects addLiquidity exceeding maxLiquidityAdd", async function () {
    const { policy, lp } = await deploy();
    await policy.setLPPolicy(lp.address, true, 10_000, 5_000, 500, 3_600);
    await expect(policy.validateLiquidityAdd(lp.address, 10_001, 100))
      .to.be.revertedWith("POLICY_LIQUIDITY_TOO_LARGE");
    await expect(policy.validateLiquidityAdd(lp.address, 100, 10_001))
      .to.be.revertedWith("POLICY_LIQUIDITY_TOO_LARGE");
  });

  it("rejects removeLiquidity exceeding maxLiquidityRemove", async function () {
    const { policy, lp } = await deploy();
    await policy.setLPPolicy(lp.address, true, 10_000, 5_000, 500, 3_600);
    await expect(policy.validateLiquidityRemove(lp.address, 5_001))
      .to.be.revertedWith("POLICY_REMOVE_TOO_LARGE");
  });

  it("rejects fee withdrawal exceeding maxFeeWithdrawal", async function () {
    const { policy, lp, recorder } = await deploy();
    await policy.setLPPolicy(lp.address, true, 10_000, 5_000, 500, 3_600);
    await policy.setRecorder(recorder.address, true);
    await policy.connect(recorder).recordFeeWithdrawal(lp.address, 400);
    await expect(policy.validateFeeWithdrawal(lp.address, 101))
      .to.be.revertedWith("POLICY_FEE_WITHDRAWAL_LIMIT");
  });

  it("resets fee withdrawal after window expiry", async function () {
    const { policy, lp, recorder } = await deploy();
    await policy.setLPPolicy(lp.address, true, 10_000, 5_000, 500, 60);
    await policy.setRecorder(recorder.address, true);
    await policy.connect(recorder).recordFeeWithdrawal(lp.address, 400);
    await increaseTime(61);
    expect(await policy.currentFeeWithdrawn(lp.address)).to.equal(0);
    await expect(policy.validateFeeWithdrawal(lp.address, 500)).to.not.be.reverted;
  });

  // ── Recorder access ───────────────────────────────────────────────────────

  it("blocks non-recorders from recording spending or fee withdrawals", async function () {
    const { policy, trader, lp, outsider } = await deploy();
    await policy.setTraderPolicy(trader.address, true, 1_000, 50_000, 3_600);
    await policy.setLPPolicy(lp.address, true, 10_000, 5_000, 500, 3_600);
    await expect(policy.connect(outsider).recordSpending(trader.address, 1))
      .to.be.revertedWith("POLICY_NOT_RECORDER");
    await expect(policy.connect(outsider).recordFeeWithdrawal(lp.address, 1))
      .to.be.revertedWith("POLICY_NOT_RECORDER");
  });

  // ── Owner-only config ─────────────────────────────────────────────────────

  it("restricts all configuration to the owner", async function () {
    const { policy, trader, lp, token, recorder, outsider } = await deploy();
    await expect(policy.connect(outsider).setTokenApproval(token.address, true))
      .to.be.revertedWithCustomError(policy, "OwnableUnauthorizedAccount");
    await expect(policy.connect(outsider).setTraderPolicy(trader.address, true, 1, 1, 60))
      .to.be.revertedWithCustomError(policy, "OwnableUnauthorizedAccount");
    await expect(policy.connect(outsider).setLPPolicy(lp.address, true, 1, 1, 1, 60))
      .to.be.revertedWithCustomError(policy, "OwnableUnauthorizedAccount");
    await expect(policy.connect(outsider).setRecorder(recorder.address, true))
      .to.be.revertedWithCustomError(policy, "OwnableUnauthorizedAccount");
  });
});
