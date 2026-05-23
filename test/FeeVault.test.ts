import { expect } from "chai";
import { ethers } from "hardhat";
import { HardhatEthersSigner } from "@nomicfoundation/hardhat-ethers/signers";

describe("FeeVault", function () {
  let vault: any;
  let policy: any;
  let tokenA: any;
  let tokenB: any;
  let lpToken: any;
  let owner: HardhatEthersSigner;
  let pool: HardhatEthersSigner;
  let lp: HardhatEthersSigner;
  let outsider: HardhatEthersSigner;
  let recorder: HardhatEthersSigner;

  const INITIAL_SUPPLY = ethers.parseEther("1000000");

  beforeEach(async function () {
    [owner, pool, lp, outsider, recorder] = await ethers.getSigners();

    const MockERC20 = await ethers.getContractFactory("MockERC20");
    tokenA = await MockERC20.deploy("Token A", "TKA", INITIAL_SUPPLY);
    tokenB = await MockERC20.deploy("Token B", "TKB", INITIAL_SUPPLY);
    lpToken = await MockERC20.deploy("LP Token", "ALP", INITIAL_SUPPLY);

    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    policy = await AgentPolicy.deploy();

    const FeeVaultFactory = await ethers.getContractFactory("FeeVault");
    vault = await FeeVaultFactory.deploy(
      await policy.getAddress(),
      await tokenA.getAddress(),
      await tokenB.getAddress(),
      await lpToken.getAddress()
    );

    await vault.setPool(pool.address);

    // Give the vault some tokens to pay out (simulating fees transferred by pool)
    await tokenA.transfer(await vault.getAddress(), ethers.parseEther("10000"));
    await tokenB.transfer(await vault.getAddress(), ethers.parseEther("10000"));
  });

  async function notifyFees(amtA: bigint, amtB: bigint) {
    if (amtA > 0n) await vault.connect(pool).notifyFee(await tokenA.getAddress(), amtA);
    if (amtB > 0n) await vault.connect(pool).notifyFee(await tokenB.getAddress(), amtB);
  }

  // ── setPool ─────────────────────────────────────────────────────────────────

  it("blocks second setPool call", async function () {
    await expect(vault.setPool(pool.address))
      .to.be.revertedWith("FEEVAULT_POOL_ALREADY_SET");
  });

  it("rejects zero pool address", async function () {
    const FeeVaultFactory = await ethers.getContractFactory("FeeVault");
    const fresh = await FeeVaultFactory.deploy(
      await policy.getAddress(),
      await tokenA.getAddress(),
      await tokenB.getAddress(),
      await lpToken.getAddress()
    );
    await expect(fresh.setPool(ethers.ZeroAddress))
      .to.be.revertedWith("FEEVAULT_ZERO_POOL");
  });

  // ── notifyFee ───────────────────────────────────────────────────────────────

  it("pool can notify fees for tokenA and tokenB", async function () {
    const feeA = ethers.parseEther("10");
    const feeB = ethers.parseEther("5");
    await notifyFees(feeA, feeB);
    expect(await vault.totalFeesA()).to.equal(feeA);
    expect(await vault.totalFeesB()).to.equal(feeB);
  });

  it("rejects notifyFee from non-pool", async function () {
    await expect(vault.connect(outsider).notifyFee(await tokenA.getAddress(), 100))
      .to.be.revertedWith("FEEVAULT_NOT_POOL");
  });

  it("rejects notifyFee for invalid token", async function () {
    const MockERC20 = await ethers.getContractFactory("MockERC20");
    const rogue = await MockERC20.deploy("R", "R", 100n);
    await expect(vault.connect(pool).notifyFee(await rogue.getAddress(), 100))
      .to.be.revertedWith("FEEVAULT_INVALID_TOKEN");
  });

  it("emits FeeNotified event", async function () {
    const fee = ethers.parseEther("1");
    await expect(vault.connect(pool).notifyFee(await tokenA.getAddress(), fee))
      .to.emit(vault, "FeeNotified")
      .withArgs(await tokenA.getAddress(), fee);
  });

  // ── collectFees ──────────────────────────────────────────────────────────────

  it("LP collects proportional share of fees", async function () {
    const totalLP = await lpToken.totalSupply();
    // lp holds half of total supply
    const lpHalf = totalLP / 2n;
    await lpToken.transfer(lp.address, lpHalf);

    const feeA = ethers.parseEther("100");
    const feeB = ethers.parseEther("200");
    await notifyFees(feeA, feeB);

    // Set up LP policy to allow withdrawal
    await policy.setLPPolicy(
      lp.address,
      true,
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      3600
    );
    await policy.setRecorder(await vault.getAddress(), true);

    const balA_before = await tokenA.balanceOf(lp.address);
    const balB_before = await tokenB.balanceOf(lp.address);

    await vault.connect(lp).collectFees(lpHalf);

    const balA_after = await tokenA.balanceOf(lp.address);
    const balB_after = await tokenB.balanceOf(lp.address);

    // lp owns lpHalf / totalLP of fees
    const expectedA = feeA * lpHalf / totalLP;
    const expectedB = feeB * lpHalf / totalLP;
    expect(balA_after - balA_before).to.equal(expectedA);
    expect(balB_after - balB_before).to.equal(expectedB);
  });

  it("collectFees reduces totalFeesA and totalFeesB", async function () {
    const totalLP = await lpToken.totalSupply();
    await lpToken.transfer(lp.address, totalLP); // lp owns all

    const feeA = ethers.parseEther("50");
    const feeB = ethers.parseEther("30");
    await notifyFees(feeA, feeB);

    await policy.setLPPolicy(
      lp.address,
      true,
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      3600
    );
    await policy.setRecorder(await vault.getAddress(), true);

    await vault.connect(lp).collectFees(totalLP);

    expect(await vault.totalFeesA()).to.equal(0n);
    expect(await vault.totalFeesB()).to.equal(0n);
  });

  it("does not allow the same LP shares to collect the same fees twice", async function () {
    const totalLP = await lpToken.totalSupply();
    const lpHalf = totalLP / 2n;
    await lpToken.transfer(lp.address, lpHalf);

    const feeA = ethers.parseEther("100");
    await notifyFees(feeA, 0n);

    await policy.setLPPolicy(
      lp.address,
      true,
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      3600
    );
    await policy.setRecorder(await vault.getAddress(), true);

    await vault.connect(lp).collectFees(lpHalf);

    await expect(vault.connect(lp).collectFees(lpHalf))
      .to.be.revertedWith("FEEVAULT_ZERO_FEES");
  });

  it("reverts collectFees with zero lpShares", async function () {
    await expect(vault.connect(lp).collectFees(0))
      .to.be.revertedWith("FEEVAULT_ZERO_SHARES");
  });

  it("reverts collectFees when LP has insufficient shares", async function () {
    await notifyFees(ethers.parseEther("10"), 0n);
    await policy.setLPPolicy(
      lp.address,
      true,
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      3600
    );
    // lp has 0 lpToken balance
    await expect(vault.connect(lp).collectFees(1000n))
      .to.be.revertedWith("FEEVAULT_INSUFFICIENT_SHARES");
  });

  it("reverts collectFees when computed fees are zero", async function () {
    const totalLP = await lpToken.totalSupply();
    // lp gets a tiny share; with 0 notified fees nothing to collect
    await lpToken.transfer(lp.address, 1n);
    await policy.setLPPolicy(
      lp.address,
      true,
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      3600
    );
    // Don't notify any fees → totalFeesA and totalFeesB are 0
    await expect(vault.connect(lp).collectFees(1n))
      .to.be.revertedWith("FEEVAULT_ZERO_FEES");
  });

  it("emits FeesCollected event", async function () {
    const totalLP = await lpToken.totalSupply();
    await lpToken.transfer(lp.address, totalLP);
    await notifyFees(ethers.parseEther("10"), ethers.parseEther("5"));

    await policy.setLPPolicy(
      lp.address,
      true,
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      ethers.parseEther("1000000"),
      3600
    );
    await policy.setRecorder(await vault.getAddress(), true);

    await expect(vault.connect(lp).collectFees(totalLP))
      .to.emit(vault, "FeesCollected");
  });

  // ── constructor guards ───────────────────────────────────────────────────────

  it("rejects zero-address constructor args", async function () {
    const FeeVaultFactory = await ethers.getContractFactory("FeeVault");
    const addr = await tokenA.getAddress();
    await expect(
      FeeVaultFactory.deploy(ethers.ZeroAddress, addr, addr, addr)
    ).to.be.revertedWith("FEEVAULT_ZERO_POLICY");
    await expect(
      FeeVaultFactory.deploy(await policy.getAddress(), ethers.ZeroAddress, addr, addr)
    ).to.be.revertedWith("FEEVAULT_ZERO_TOKEN_A");
    await expect(
      FeeVaultFactory.deploy(await policy.getAddress(), addr, ethers.ZeroAddress, addr)
    ).to.be.revertedWith("FEEVAULT_ZERO_TOKEN_B");
    await expect(
      FeeVaultFactory.deploy(await policy.getAddress(), addr, addr, ethers.ZeroAddress)
    ).to.be.revertedWith("FEEVAULT_ZERO_LP_TOKEN");
  });
});
