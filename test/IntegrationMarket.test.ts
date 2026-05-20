import { expect } from "chai";
import { ethers } from "hardhat";

describe("IntegrationMarket", function () {
  async function deployMarket() {
    const [owner, firm, trader, buyer, outsider] = await ethers.getSigners();

    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    const policy = await AgentPolicy.deploy();

    const MockERC20 = await ethers.getContractFactory("MockERC20");
    const paymentToken = await MockERC20.deploy("USD Coin", "USDC", 1_000_000);

    const StockToken = await ethers.getContractFactory("StockToken");
    const stockToken = await StockToken.deploy("ACME Corp", "ACME", firm.address, 1_000);

    const Exchange = await ethers.getContractFactory("Exchange");
    const exchange = await Exchange.deploy(await policy.getAddress(), await paymentToken.getAddress());

    const DividendVault = await ethers.getContractFactory("DividendVault");
    const dividendVault = await DividendVault.deploy(await policy.getAddress(), await paymentToken.getAddress());

    const stockAddr = await stockToken.getAddress();
    const exchangeAddr = await exchange.getAddress();
    const dividendVaultAddr = await dividendVault.getAddress();

    await policy.setTokenPolicy(stockAddr, true, 500, false);
    await policy.setTraderPolicy(firm.address, true, 500, 100_000, 3_600);
    await policy.setTraderPolicy(trader.address, true, 500, 100_000, 3_600);
    await policy.setTraderPolicy(buyer.address, true, 500, 100_000, 3_600);
    await policy.setDividendPolicy(firm.address, true, 2_000, 3_600);
    await policy.setRecorder(exchangeAddr, true);
    await policy.setRecorder(dividendVaultAddr, true);

    await stockToken.connect(firm).mint(firm.address, 500);
    await stockToken.connect(firm).mint(trader.address, 300);
    await stockToken.connect(firm).mint(buyer.address, 200);

    await paymentToken.transfer(firm.address, 20_000);
    await paymentToken.transfer(trader.address, 20_000);
    await paymentToken.transfer(buyer.address, 20_000);

    await paymentToken.connect(firm).approve(dividendVaultAddr, ethers.MaxUint256);
    await paymentToken.connect(trader).approve(exchangeAddr, ethers.MaxUint256);
    await paymentToken.connect(buyer).approve(exchangeAddr, ethers.MaxUint256);
    await stockToken.connect(firm).approve(exchangeAddr, ethers.MaxUint256);
    await stockToken.connect(trader).approve(exchangeAddr, ethers.MaxUint256);
    await stockToken.connect(buyer).approve(exchangeAddr, ethers.MaxUint256);

    return {
      policy,
      paymentToken,
      stockToken,
      exchange,
      dividendVault,
      owner,
      firm,
      trader,
      buyer,
      outsider,
      stockAddr,
    };
  }

  it("settles buys, sells, and dividends across the deployed market", async function () {
    const { paymentToken, stockToken, exchange, dividendVault, firm, trader, buyer, stockAddr } =
      await deployMarket();

    await exchange.connect(firm).createSellOrder(stockAddr, 100, 1_000);
    await expect(exchange.connect(trader).buy(stockAddr, firm.address, 100, 1_000))
      .to.emit(exchange, "TradeSettled")
      .withArgs(trader.address, stockAddr, firm.address, 100, 1_000, true);

    expect(await stockToken.balanceOf(trader.address)).to.equal(400);
    expect(await stockToken.balanceOf(firm.address)).to.equal(400);
    expect(await paymentToken.balanceOf(trader.address)).to.equal(19_000);
    expect(await paymentToken.balanceOf(firm.address)).to.equal(21_000);

    await exchange.connect(buyer).createBuyOrder(stockAddr, 50, 500);
    await expect(exchange.connect(trader).sell(stockAddr, buyer.address, 50, 500))
      .to.emit(exchange, "TradeSettled")
      .withArgs(trader.address, stockAddr, buyer.address, 50, 500, false);

    expect(await stockToken.balanceOf(trader.address)).to.equal(350);
    expect(await stockToken.balanceOf(buyer.address)).to.equal(250);
    expect(await paymentToken.balanceOf(trader.address)).to.equal(19_500);
    expect(await paymentToken.balanceOf(buyer.address)).to.equal(19_500);

    await dividendVault.connect(firm).deposit(1_000);
    await expect(
      dividendVault.connect(firm).distribute(stockAddr, [firm.address, trader.address, buyer.address], 1_000)
    )
      .to.emit(dividendVault, "DividendPaid")
      .withArgs(firm.address, stockAddr, firm.address, 400)
      .and.to.emit(dividendVault, "DividendPaid")
      .withArgs(firm.address, stockAddr, trader.address, 350)
      .and.to.emit(dividendVault, "DividendPaid")
      .withArgs(firm.address, stockAddr, buyer.address, 250);

    expect(await paymentToken.balanceOf(firm.address)).to.equal(20_400);
    expect(await paymentToken.balanceOf(trader.address)).to.equal(19_850);
    expect(await paymentToken.balanceOf(buyer.address)).to.equal(19_750);
  });

  it("reverts oversized trades, unauthorized assets, excessive minting, and excessive dividends", async function () {
    const { stockToken, exchange, dividendVault, firm, trader, buyer, outsider, stockAddr } = await deployMarket();

    await expect(exchange.connect(firm).createSellOrder(stockAddr, 501, 1_000)).to.be.revertedWith(
      "POLICY_TRADE_TOO_LARGE"
    );

    const StockToken = await ethers.getContractFactory("StockToken");
    const unapprovedStock = await StockToken.deploy("Other Corp", "OTHR", outsider.address, 1_000);
    await expect(
      exchange.connect(trader).buy(await unapprovedStock.getAddress(), firm.address, 1, 1)
    ).to.be.revertedWith("POLICY_TOKEN_NOT_APPROVED");

    await expect(stockToken.connect(firm).mint(firm.address, 1)).to.be.revertedWith("TOKEN_CAP_EXCEEDED");

    await dividendVault.connect(firm).deposit(3_000);
    await expect(
      dividendVault.connect(firm).distribute(stockAddr, [firm.address, trader.address, buyer.address], 3_000)
    ).to.be.revertedWith("POLICY_DIVIDEND_BUDGET");
  });
});
