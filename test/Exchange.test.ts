import { expect } from "chai";
import { ethers } from "hardhat";

describe("Exchange", function () {
  async function deploy() {
    const [owner, trader, firm, buyer] = await ethers.getSigners();

    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    const policy = await AgentPolicy.deploy();

    const MockERC20 = await ethers.getContractFactory("MockERC20");
    const paymentToken = await MockERC20.deploy("USD Coin", "USDC", 1_000_000);

    const StockToken = await ethers.getContractFactory("StockToken");
    const stockToken = await StockToken.deploy("ACME Corp", "ACME", firm.address, 500_000);

    const Exchange = await ethers.getContractFactory("Exchange");
    const exchange = await Exchange.deploy(await policy.getAddress(), await paymentToken.getAddress());

    const exchangeAddr = await exchange.getAddress();
    const stockAddr = await stockToken.getAddress();

    // Exchange must be an approved recorder so it can call policy.recordSpending
    await policy.setRecorder(exchangeAddr, true);
    await policy.setTokenPolicy(stockAddr, true, 500, false);
    await policy.setTraderPolicy(firm.address, true, 500, 100_000, 3_600);
    await policy.setTraderPolicy(trader.address, true, 500, 100_000, 3_600);
    await policy.setTraderPolicy(buyer.address, true, 500, 100_000, 3_600);

    // Mint stock tokens: firm holds shares for buy-flow, trader holds shares for sell-flow
    await stockToken.connect(firm).mint(firm.address, 10_000);
    await stockToken.connect(firm).mint(trader.address, 10_000);

    // Distribute payment tokens
    await paymentToken.transfer(trader.address, 50_000);
    await paymentToken.transfer(buyer.address, 50_000);

    // Approve exchange to move tokens on behalf of every party
    await paymentToken.connect(trader).approve(exchangeAddr, ethers.MaxUint256);
    await stockToken.connect(firm).approve(exchangeAddr, ethers.MaxUint256);
    await stockToken.connect(trader).approve(exchangeAddr, ethers.MaxUint256);
    await paymentToken.connect(buyer).approve(exchangeAddr, ethers.MaxUint256);

    return { policy, paymentToken, stockToken, exchange, owner, trader, firm, buyer };
  }

  it("settles a buy order and updates balances", async function () {
    const { paymentToken, stockToken, exchange, trader, firm } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await exchange.connect(firm).createSellOrder(stockAddr, 100, 500);
    await exchange.connect(trader).buy(stockAddr, firm.address, 100, 500);

    expect(await paymentToken.balanceOf(trader.address)).to.equal(50_000 - 500);
    expect(await paymentToken.balanceOf(firm.address)).to.equal(500);
    expect(await stockToken.balanceOf(trader.address)).to.equal(10_000 + 100);
    expect(await stockToken.balanceOf(firm.address)).to.equal(10_000 - 100);
  });

  it("settles a sell order and updates balances", async function () {
    const { paymentToken, stockToken, exchange, trader, buyer } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await exchange.connect(buyer).createBuyOrder(stockAddr, 100, 500);
    await exchange.connect(trader).sell(stockAddr, buyer.address, 100, 500);

    expect(await stockToken.balanceOf(trader.address)).to.equal(10_000 - 100);
    expect(await stockToken.balanceOf(buyer.address)).to.equal(100);
    expect(await paymentToken.balanceOf(trader.address)).to.equal(50_000 + 500);
    expect(await paymentToken.balanceOf(buyer.address)).to.equal(50_000 - 500);
  });

  it("reverts when share amount exceeds the trader's max trade size", async function () {
    const { stockToken, exchange, trader, firm } = await deploy();

    await expect(
      exchange.connect(trader).buy(await stockToken.getAddress(), firm.address, 501, 1)
    ).to.be.revertedWith("POLICY_TRADE_TOO_LARGE");
  });

  it("reverts when share amount exceeds the token's max trade size", async function () {
    const { policy, stockToken, exchange, trader, firm } = await deploy();
    // Raise personal limit above token limit so token constraint is the binding one
    await policy.setTraderPolicy(trader.address, true, 1_000, 100_000, 3_600);

    await expect(
      exchange.connect(trader).buy(await stockToken.getAddress(), firm.address, 501, 1)
    ).to.be.revertedWith("POLICY_TOKEN_TRADE_TOO_LARGE");
  });

  it("reverts when the stock token is not approved in policy", async function () {
    const { exchange, trader, firm } = await deploy();
    const [, , , , , unapproved] = await ethers.getSigners();

    await expect(
      exchange.connect(trader).buy(unapproved.address, firm.address, 1, 1)
    ).to.be.revertedWith("POLICY_TOKEN_NOT_APPROVED");
  });

  it("reverts when cumulative payment would exceed the spending limit", async function () {
    const { policy, stockToken, exchange, trader, firm } = await deploy();
    const stockAddr = await stockToken.getAddress();

    // Tighten the spending window to 1 000
    await policy.setTraderPolicy(trader.address, true, 500, 1_000, 3_600);

    await exchange.connect(firm).createSellOrder(stockAddr, 100, 800);
    await exchange.connect(trader).buy(stockAddr, firm.address, 100, 800);

    // 800 already spent; 201 more would exceed the 1 000 limit
    await expect(
      exchange.connect(trader).buy(stockAddr, firm.address, 10, 201)
    ).to.be.revertedWith("POLICY_SPENDING_LIMIT");
  });

  it("requires a sell order before a buyer can pull seller shares", async function () {
    const { stockToken, exchange, trader, firm } = await deploy();

    await expect(
      exchange.connect(trader).buy(await stockToken.getAddress(), firm.address, 100, 500)
    ).to.be.revertedWith("EXCHANGE_SELL_ORDER_NOT_OPEN");
  });

  it("requires a buy order before a seller can pull buyer payment", async function () {
    const { stockToken, exchange, trader, buyer } = await deploy();

    await expect(
      exchange.connect(trader).sell(await stockToken.getAddress(), buyer.address, 100, 500)
    ).to.be.revertedWith("EXCHANGE_BUY_ORDER_NOT_OPEN");
  });

  it("rejects zero-share or zero-payment orders", async function () {
    const { stockToken, exchange, trader, firm, buyer } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await expect(exchange.connect(firm).createSellOrder(stockAddr, 0, 500)).to.be.revertedWith(
      "EXCHANGE_ZERO_SHARES"
    );
    await expect(exchange.connect(firm).createSellOrder(stockAddr, 100, 0)).to.be.revertedWith(
      "EXCHANGE_ZERO_PAYMENT"
    );
    await expect(exchange.connect(buyer).createBuyOrder(stockAddr, 0, 500)).to.be.revertedWith(
      "EXCHANGE_ZERO_SHARES"
    );
    await expect(exchange.connect(trader).sell(stockAddr, buyer.address, 100, 0)).to.be.revertedWith(
      "EXCHANGE_ZERO_PAYMENT"
    );
  });

  it("reverts sell orders when the buyer agent is disabled", async function () {
    const { policy, stockToken, exchange, trader, buyer } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await exchange.connect(buyer).createBuyOrder(stockAddr, 100, 500);
    await policy.setTraderPolicy(buyer.address, false, 500, 100_000, 3_600);

    await expect(exchange.connect(trader).sell(stockAddr, buyer.address, 100, 500)).to.be.revertedWith(
      "POLICY_TRADER_DISABLED"
    );
  });

  it("records buyer spending when a sell order settles", async function () {
    const { policy, stockToken, exchange, trader, buyer } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await exchange.connect(buyer).createBuyOrder(stockAddr, 100, 500);
    await exchange.connect(trader).sell(stockAddr, buyer.address, 100, 500);

    expect(await policy.currentSpentAmount(buyer.address)).to.equal(500);
  });

  it("emits TradeSettled for successful buy and sell", async function () {
    const { stockToken, exchange, trader, firm, buyer } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await exchange.connect(firm).createSellOrder(stockAddr, 50, 250);
    await expect(exchange.connect(trader).buy(stockAddr, firm.address, 50, 250))
      .to.emit(exchange, "TradeSettled")
      .withArgs(trader.address, stockAddr, firm.address, 50, 250, true);

    await exchange.connect(buyer).createBuyOrder(stockAddr, 50, 250);
    await expect(exchange.connect(trader).sell(stockAddr, buyer.address, 50, 250))
      .to.emit(exchange, "TradeSettled")
      .withArgs(trader.address, stockAddr, buyer.address, 50, 250, false);
  });
});
