import { expect } from "chai";
import { ethers } from "hardhat";

describe("IntegrationMarket", function () {
  const INITIAL_SUPPLY = ethers.parseEther("1000000");
  const INITIAL_LP_STOCK = ethers.parseEther("1000");
  const INITIAL_LP_USD = ethers.parseEther("100000");
  const TRADER_USD = ethers.parseEther("10000");
  const TRADER_STOCK = ethers.parseEther("100");
  const MAX_SWAP = ethers.parseEther("1000");
  const SPENDING_LIMIT = ethers.parseEther("100000");
  const LP_LIMIT = ethers.parseEther("1000000");
  const WINDOW = 3600;

  async function deployPool(
    policy: any,
    stockToken: any,
    usdToken: any,
    name: string,
    symbol: string
  ) {
    const LPToken = await ethers.getContractFactory("LPToken");
    const lpToken: any = await LPToken.deploy(name, symbol);

    const FeeVault = await ethers.getContractFactory("FeeVault");
    const vault: any = await FeeVault.deploy(
      await policy.getAddress(),
      await stockToken.getAddress(),
      await usdToken.getAddress(),
      await lpToken.getAddress()
    );

    const AMMPool = await ethers.getContractFactory("AMMPool");
    const pool: any = await AMMPool.deploy(
      await policy.getAddress(),
      await stockToken.getAddress(),
      await usdToken.getAddress(),
      await lpToken.getAddress(),
      await vault.getAddress()
    );

    await lpToken.setPool(await pool.getAddress());
    await vault.setPool(await pool.getAddress());
    await policy.setRecorder(await pool.getAddress(), true);
    await policy.setRecorder(await vault.getAddress(), true);

    return { lpToken, vault, pool };
  }

  async function deployMarket() {
    const [owner, lp, trader, outsider] = await ethers.getSigners();

    const MockERC20 = await ethers.getContractFactory("MockERC20");
    const usd: any = await MockERC20.deploy("Mock USD", "USD", INITIAL_SUPPLY);
    const aapl: any = await MockERC20.deploy("Apple Demo", "AAPL", INITIAL_SUPPLY);
    const nvda: any = await MockERC20.deploy("Nvidia Demo", "NVDA", INITIAL_SUPPLY);

    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    const policy: any = await AgentPolicy.deploy();

    const aaplMarket = await deployPool(policy, aapl, usd, "AAPL USD LP", "AAPLUSD-LP");
    const nvdaMarket = await deployPool(policy, nvda, usd, "NVDA USD LP", "NVDAUSD-LP");

    for (const token of [usd, aapl, nvda]) {
      await policy.setTokenApproval(await token.getAddress(), true);
    }

    await policy.setTraderPolicy(trader.address, true, MAX_SWAP, SPENDING_LIMIT, WINDOW);
    await policy.setLPPolicy(lp.address, true, LP_LIMIT, LP_LIMIT, LP_LIMIT, WINDOW);

    for (const stock of [aapl, nvda]) {
      await stock.transfer(lp.address, INITIAL_LP_STOCK);
      await stock.transfer(trader.address, TRADER_STOCK);
      await stock.transfer(outsider.address, ethers.parseEther("10"));
    }
    await usd.transfer(lp.address, INITIAL_LP_USD * 2n);
    await usd.transfer(trader.address, TRADER_USD);
    await usd.transfer(outsider.address, ethers.parseEther("1000"));

    for (const market of [aaplMarket, nvdaMarket]) {
      await usd.connect(lp).approve(await market.pool.getAddress(), ethers.MaxUint256);
      await usd.connect(trader).approve(await market.pool.getAddress(), ethers.MaxUint256);
      await usd.connect(outsider).approve(await market.pool.getAddress(), ethers.MaxUint256);
    }

    await aapl.connect(lp).approve(await aaplMarket.pool.getAddress(), ethers.MaxUint256);
    await aapl.connect(trader).approve(await aaplMarket.pool.getAddress(), ethers.MaxUint256);
    await aapl.connect(outsider).approve(await aaplMarket.pool.getAddress(), ethers.MaxUint256);

    await nvda.connect(lp).approve(await nvdaMarket.pool.getAddress(), ethers.MaxUint256);
    await nvda.connect(trader).approve(await nvdaMarket.pool.getAddress(), ethers.MaxUint256);

    return { owner, lp, trader, outsider, policy, usd, aapl, nvda, aaplMarket, nvdaMarket };
  }

  it("runs the multi-pool AMM flow and enforces policy failures", async function () {
    const { lp, trader, outsider, policy, usd, aapl, nvda, aaplMarket, nvdaMarket } =
      await deployMarket();

    await expect(
      aaplMarket.pool.connect(lp).addLiquidity(
        ethers.parseEther("100"),
        ethers.parseEther("10000"),
        0
      )
    ).to.emit(aaplMarket.pool, "LiquidityAdded");

    await expect(
      nvdaMarket.pool.connect(lp).addLiquidity(
        ethers.parseEther("100"),
        ethers.parseEther("20000"),
        0
      )
    ).to.emit(nvdaMarket.pool, "LiquidityAdded");

    expect(await aaplMarket.pool.reserveA()).to.equal(ethers.parseEther("100"));
    expect(await aaplMarket.pool.reserveB()).to.equal(ethers.parseEther("10000"));
    expect(await nvdaMarket.pool.reserveA()).to.equal(ethers.parseEther("100"));
    expect(await nvdaMarket.pool.reserveB()).to.equal(ethers.parseEther("20000"));

    const swapAmount = ethers.parseEther("100");
    const expectedFee = swapAmount * 30n / 10_000n;
    const traderAaplBefore = await aapl.balanceOf(trader.address);

    await expect(
      aaplMarket.pool.connect(trader).swap(
        await usd.getAddress(),
        swapAmount,
        0,
        ethers.MaxUint256
      )
    ).to.emit(aaplMarket.pool, "Swap");

    expect(await aapl.balanceOf(trader.address)).to.be.gt(traderAaplBefore);
    expect(await aaplMarket.vault.totalFeesB()).to.equal(expectedFee);
    expect(await usd.balanceOf(await aaplMarket.vault.getAddress())).to.equal(expectedFee);
    expect(await policy.currentSpentAmount(trader.address)).to.equal(swapAmount);

    const lpUsdBeforeFees = await usd.balanceOf(lp.address);
    const aaplLpShares = await aaplMarket.lpToken.balanceOf(lp.address);
    await expect(aaplMarket.vault.connect(lp).collectFees(aaplLpShares))
      .to.emit(aaplMarket.vault, "FeesCollected");
    expect(await usd.balanceOf(lp.address)).to.equal(lpUsdBeforeFees + expectedFee);
    expect(await aaplMarket.vault.totalFeesB()).to.equal(0n);

    const halfShares = aaplLpShares / 2n;
    const lpAaplBeforeRemove = await aapl.balanceOf(lp.address);
    const lpUsdBeforeRemove = await usd.balanceOf(lp.address);
    await expect(aaplMarket.pool.connect(lp).removeLiquidity(halfShares))
      .to.emit(aaplMarket.pool, "LiquidityRemoved");
    expect(await aapl.balanceOf(lp.address)).to.be.gt(lpAaplBeforeRemove);
    expect(await usd.balanceOf(lp.address)).to.be.gt(lpUsdBeforeRemove);
    expect(await aaplMarket.lpToken.balanceOf(lp.address)).to.equal(aaplLpShares - halfShares);

    const oversizedSwap = MAX_SWAP + 1n;
    await expect(
      nvdaMarket.pool.connect(trader).swap(
        await usd.getAddress(),
        oversizedSwap,
        0,
        ethers.MaxUint256
      )
    ).to.be.revertedWith("POLICY_SWAP_TOO_LARGE");

    await policy.setTokenApproval(await nvda.getAddress(), false);
    await expect(
      nvdaMarket.pool.connect(trader).swap(
        await nvda.getAddress(),
        ethers.parseEther("1"),
        0,
        ethers.MaxUint256
      )
    ).to.be.revertedWith("POLICY_TOKEN_NOT_APPROVED");

    await expect(
      aaplMarket.pool.connect(outsider).addLiquidity(
        ethers.parseEther("1"),
        ethers.parseEther("100"),
        0
      )
    ).to.be.revertedWith("POLICY_LP_DISABLED");
  });
});
