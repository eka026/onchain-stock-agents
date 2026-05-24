import { expect } from "chai";
import { ethers } from "hardhat";
import { HardhatEthersSigner } from "@nomicfoundation/hardhat-ethers/signers";

describe("AMMPool", function () {
  let pool: any;
  let lpToken: any;
  let policy: any;
  let feeVault: any;
  let tokenA: any;
  let tokenB: any;
  let owner: HardhatEthersSigner;
  let lp: HardhatEthersSigner;
  let trader: HardhatEthersSigner;

  const INITIAL_SUPPLY = ethers.parseEther("1000000");

  beforeEach(async function () {
    [owner, lp, trader] = await ethers.getSigners();

    const MockERC20 = await ethers.getContractFactory("MockERC20");
    tokenA = await MockERC20.deploy("Token A", "TKA", INITIAL_SUPPLY);
    tokenB = await MockERC20.deploy("Token B", "TKB", INITIAL_SUPPLY);

    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    policy = await AgentPolicy.deploy();

    const LPTokenFactory = await ethers.getContractFactory("LPToken");
    lpToken = await LPTokenFactory.deploy("AMM LP", "ALP");

    const FeeVaultFactory = await ethers.getContractFactory("FeeVault");
    feeVault = await FeeVaultFactory.deploy(
      await policy.getAddress(),
      await tokenA.getAddress(),
      await tokenB.getAddress(),
      await lpToken.getAddress()
    );

    const AMMPoolFactory = await ethers.getContractFactory("AMMPool");
    pool = await AMMPoolFactory.deploy(
      await policy.getAddress(),
      await tokenA.getAddress(),
      await tokenB.getAddress(),
      await lpToken.getAddress(),
      await feeVault.getAddress()
    );

    await lpToken.setPool(await pool.getAddress());
    await feeVault.setPool(await pool.getAddress());

    // Fund lp and trader
    await tokenA.transfer(lp.address, ethers.parseEther("10000"));
    await tokenB.transfer(lp.address, ethers.parseEther("10000"));
    await tokenA.transfer(trader.address, ethers.parseEther("1000"));
    await tokenB.transfer(trader.address, ethers.parseEther("1000"));

    // Set up policy for lp
    await policy.setLPPolicy(
      lp.address,
      true,
      ethers.parseEther("100000"),
      ethers.parseEther("100000"),
      ethers.parseEther("100000"),
      3600
    );

    // Set up policy for trader
    await policy.setTokenApproval(await tokenA.getAddress(), true);
    await policy.setTokenApproval(await tokenB.getAddress(), true);
    await policy.setTraderPolicy(
      trader.address,
      true,
      ethers.parseEther("1000"),
      ethers.parseEther("100000"),
      3600
    );

    // Pool contract records spending and fee withdrawals
    await policy.setRecorder(await pool.getAddress(), true);
  });

  async function addInitialLiquidity(amountA: bigint, amountB: bigint) {
    await tokenA.connect(lp).approve(await pool.getAddress(), amountA);
    await tokenB.connect(lp).approve(await pool.getAddress(), amountB);
    return pool.connect(lp).addLiquidity(amountA, amountB, 0);
  }

  // ── addLiquidity ────────────────────────────────────────────────────────────

  it("first addLiquidity mints sqrt(amountA * amountB) LP shares", async function () {
    const amountA = ethers.parseEther("100");
    const amountB = ethers.parseEther("400");
    await addInitialLiquidity(amountA, amountB);

    const expectedShares = BigInt(Math.floor(Math.sqrt(Number(amountA) * Number(amountB))));
    const actual = await lpToken.balanceOf(lp.address);
    // Allow 1 wei tolerance for integer sqrt
    expect(actual).to.be.closeTo(expectedShares, 1n);
  });

  it("subsequent addLiquidity mints proportional LP shares", async function () {
    const amountA = ethers.parseEther("100");
    const amountB = ethers.parseEther("100");
    await addInitialLiquidity(amountA, amountB);

    const firstShares = await lpToken.balanceOf(lp.address);

    // Add the same amounts again → same shares
    await tokenA.connect(lp).approve(await pool.getAddress(), amountA);
    await tokenB.connect(lp).approve(await pool.getAddress(), amountB);
    await pool.connect(lp).addLiquidity(amountA, amountB, 0);

    const totalShares = await lpToken.balanceOf(lp.address);
    expect(totalShares).to.equal(firstShares * 2n);
  });

  it("subsequent addLiquidity uses the proportional subset when one side is oversized", async function () {
    await addInitialLiquidity(ethers.parseEther("100"), ethers.parseEther("100"));
    const amountA = ethers.parseEther("10");
    const amountB = ethers.parseEther("20");
    await tokenA.connect(lp).approve(await pool.getAddress(), amountA);
    await tokenB.connect(lp).approve(await pool.getAddress(), amountB);

    await expect(pool.connect(lp).addLiquidity(amountA, amountB, 0))
      .to.emit(pool, "LiquidityAdded")
      .withArgs(lp.address, amountA, amountA, amountA);

    expect(await pool.reserveA()).to.equal(ethers.parseEther("110"));
    expect(await pool.reserveB()).to.equal(ethers.parseEther("110"));
  });

  it("reverts addLiquidity when minted LP shares are below caller minimum", async function () {
    const amountA = ethers.parseEther("100");
    const amountB = ethers.parseEther("100");
    await tokenA.connect(lp).approve(await pool.getAddress(), amountA);
    await tokenB.connect(lp).approve(await pool.getAddress(), amountB);

    await expect(pool.connect(lp).addLiquidity(amountA, amountB, amountA + 1n))
      .to.be.revertedWith("POOL_SLIPPAGE");
  });

  it("reverts addLiquidity with zero amounts", async function () {
    await expect(pool.connect(lp).addLiquidity(0, 100, 0))
      .to.be.revertedWith("POOL_ZERO_AMOUNT");
    await expect(pool.connect(lp).addLiquidity(100, 0, 0))
      .to.be.revertedWith("POOL_ZERO_AMOUNT");
  });

  it("emits LiquidityAdded event", async function () {
    const amountA = ethers.parseEther("100");
    const amountB = ethers.parseEther("100");
    await tokenA.connect(lp).approve(await pool.getAddress(), amountA);
    await tokenB.connect(lp).approve(await pool.getAddress(), amountB);
    await expect(pool.connect(lp).addLiquidity(amountA, amountB, 0))
      .to.emit(pool, "LiquidityAdded");
  });

  // ── removeLiquidity ─────────────────────────────────────────────────────────

  it("removeLiquidity returns proportional tokens and burns LP shares", async function () {
    const amountA = ethers.parseEther("100");
    const amountB = ethers.parseEther("200");
    await addInitialLiquidity(amountA, amountB);

    const shares = await lpToken.balanceOf(lp.address);
    const half = shares / 2n;

    const balA_before = await tokenA.balanceOf(lp.address);
    const balB_before = await tokenB.balanceOf(lp.address);

    await pool.connect(lp).removeLiquidity(half);

    const balA_after = await tokenA.balanceOf(lp.address);
    const balB_after = await tokenB.balanceOf(lp.address);

    expect(balA_after - balA_before).to.equal(amountA / 2n);
    expect(balB_after - balB_before).to.equal(amountB / 2n);
    expect(await lpToken.balanceOf(lp.address)).to.equal(shares - half);
  });

  it("reverts removeLiquidity with zero shares", async function () {
    await expect(pool.connect(lp).removeLiquidity(0))
      .to.be.revertedWith("POOL_ZERO_SHARES");
  });

  it("emits LiquidityRemoved event", async function () {
    await addInitialLiquidity(ethers.parseEther("100"), ethers.parseEther("100"));
    const shares = await lpToken.balanceOf(lp.address);
    await expect(pool.connect(lp).removeLiquidity(shares))
      .to.emit(pool, "LiquidityRemoved");
  });

  // ── swap ────────────────────────────────────────────────────────────────────

  it("swap A→B follows constant product formula minus fee", async function () {
    const liqA = ethers.parseEther("1000");
    const liqB = ethers.parseEther("1000");
    await addInitialLiquidity(liqA, liqB);

    const amountIn = ethers.parseEther("10");
    const feeBps = 30n;
    const fee = amountIn * feeBps / 10_000n;
    const amountInLessFee = amountIn - fee;
    const expectedOut = liqB * amountInLessFee / (liqA + amountInLessFee);

    await tokenA.connect(trader).approve(await pool.getAddress(), amountIn);
    const balB_before = await tokenB.balanceOf(trader.address);
    await pool.connect(trader).swap(await tokenA.getAddress(), amountIn, 0, ethers.MaxUint256);
    const balB_after = await tokenB.balanceOf(trader.address);

    expect(balB_after - balB_before).to.equal(expectedOut);
  });

  it("swap B→A follows constant product formula minus fee", async function () {
    const liqA = ethers.parseEther("1000");
    const liqB = ethers.parseEther("2000");
    await addInitialLiquidity(liqA, liqB);

    const amountIn = ethers.parseEther("10");
    const feeBps = 30n;
    const fee = amountIn * feeBps / 10_000n;
    const amountInLessFee = amountIn - fee;
    const expectedOut = liqA * amountInLessFee / (liqB + amountInLessFee);

    await tokenB.connect(trader).approve(await pool.getAddress(), amountIn);
    const balA_before = await tokenA.balanceOf(trader.address);
    await pool.connect(trader).swap(await tokenB.getAddress(), amountIn, 0, ethers.MaxUint256);
    const balA_after = await tokenA.balanceOf(trader.address);

    expect(balA_after - balA_before).to.equal(expectedOut);
  });

  it("swap fee is sent to FeeVault and notifyFee is called", async function () {
    await addInitialLiquidity(ethers.parseEther("1000"), ethers.parseEther("1000"));

    const amountIn = ethers.parseEther("100");
    const fee = amountIn * 30n / 10_000n;

    await tokenA.connect(trader).approve(await pool.getAddress(), amountIn);
    await pool.connect(trader).swap(await tokenA.getAddress(), amountIn, 0, ethers.MaxUint256);

    expect(await feeVault.totalFeesA()).to.equal(fee);
    expect(await tokenA.balanceOf(await feeVault.getAddress())).to.equal(fee);
  });

  it("reverts swap with invalid token", async function () {
    const MockERC20 = await ethers.getContractFactory("MockERC20");
    const rogue = await MockERC20.deploy("Rogue", "RGE", 1000n);
    await expect(pool.connect(trader).swap(await rogue.getAddress(), 1, 0, ethers.MaxUint256))
      .to.be.revertedWith("POOL_INVALID_TOKEN");
  });

  it("reverts swap with zero input", async function () {
    await expect(pool.connect(trader).swap(await tokenA.getAddress(), 0, 0, ethers.MaxUint256))
      .to.be.revertedWith("POOL_ZERO_INPUT");
  });

  it("reverts swap when output is below caller minimum", async function () {
    await addInitialLiquidity(ethers.parseEther("1000"), ethers.parseEther("1000"));
    const amountIn = ethers.parseEther("10");
    await tokenA.connect(trader).approve(await pool.getAddress(), amountIn);

    await expect(
      pool.connect(trader).swap(await tokenA.getAddress(), amountIn, ethers.parseEther("10"), ethers.MaxUint256)
    ).to.be.revertedWith("POOL_SLIPPAGE");
  });

  it("reverts swap after caller deadline", async function () {
    await addInitialLiquidity(ethers.parseEther("1000"), ethers.parseEther("1000"));
    const amountIn = ethers.parseEther("10");
    await tokenA.connect(trader).approve(await pool.getAddress(), amountIn);

    await expect(pool.connect(trader).swap(await tokenA.getAddress(), amountIn, 0, 1))
      .to.be.revertedWith("POOL_DEADLINE_EXPIRED");
  });

  it("emits Swap event", async function () {
    await addInitialLiquidity(ethers.parseEther("1000"), ethers.parseEther("1000"));
    const amountIn = ethers.parseEther("10");
    await tokenA.connect(trader).approve(await pool.getAddress(), amountIn);
    await expect(pool.connect(trader).swap(await tokenA.getAddress(), amountIn, 0, ethers.MaxUint256))
      .to.emit(pool, "Swap");
  });

  // ── spotPrice ───────────────────────────────────────────────────────────────

  it("spotPrice returns reserveB / reserveA scaled by 1e18", async function () {
    const liqA = ethers.parseEther("100");
    const liqB = ethers.parseEther("200");
    await addInitialLiquidity(liqA, liqB);
    const price = await pool.spotPrice();
    expect(price).to.equal(liqB * BigInt(1e18) / liqA);
  });

  it("spotPrice reverts when pool is empty", async function () {
    await expect(pool.spotPrice()).to.be.revertedWith("POOL_NO_LIQUIDITY");
  });

  // ── setFeeBps ───────────────────────────────────────────────────────────────

  it("owner can update feeBps within limit", async function () {
    await expect(pool.setFeeBps(50))
      .to.emit(pool, "FeeBpsUpdated")
      .withArgs(50);
    expect(await pool.feeBps()).to.equal(50);
  });

  it("owner can set feeBps to zero and emits FeeBpsUpdated", async function () {
    await expect(pool.setFeeBps(0))
      .to.emit(pool, "FeeBpsUpdated")
      .withArgs(0);
    expect(await pool.feeBps()).to.equal(0);
  });

  it("reverts setFeeBps above 1000", async function () {
    await expect(pool.setFeeBps(1001)).to.be.revertedWith("POOL_FEE_TOO_HIGH");
  });

  it("reverts setFeeBps from non-owner", async function () {
    await expect(pool.connect(trader).setFeeBps(10))
      .to.be.revertedWithCustomError(pool, "OwnableUnauthorizedAccount");
  });

  // ── policy enforcement ──────────────────────────────────────────────────────

  it("reverts swap when policy rejects trader", async function () {
    await addInitialLiquidity(ethers.parseEther("1000"), ethers.parseEther("1000"));
    const badAmount = ethers.parseEther("1001"); // exceeds maxSwapAmount
    await tokenA.connect(trader).approve(await pool.getAddress(), badAmount);
    await expect(pool.connect(trader).swap(await tokenA.getAddress(), badAmount, 0, ethers.MaxUint256))
      .to.be.revertedWith("POLICY_SWAP_TOO_LARGE");
  });

  it("reverts addLiquidity when LP policy is disabled", async function () {
    const [, , , outsider] = await ethers.getSigners();
    await tokenA.transfer(outsider.address, ethers.parseEther("100"));
    await tokenB.transfer(outsider.address, ethers.parseEther("100"));
    const amt = ethers.parseEther("10");
    await tokenA.connect(outsider).approve(await pool.getAddress(), amt);
    await tokenB.connect(outsider).approve(await pool.getAddress(), amt);
    // outsider has no LP policy → validateLiquidityAdd reverts as disabled (default struct)
    await expect(pool.connect(outsider).addLiquidity(amt, amt, 0))
      .to.be.revertedWith("POLICY_LP_DISABLED");
  });
});
