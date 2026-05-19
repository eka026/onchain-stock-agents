import { expect } from "chai";
import { ethers } from "hardhat";

describe("DividendVault", function () {
  async function deploy() {
    const [owner, firm, holderA, holderB, outsider] = await ethers.getSigners();

    const AgentPolicy = await ethers.getContractFactory("AgentPolicy");
    const policy = await AgentPolicy.deploy();

    const MockERC20 = await ethers.getContractFactory("MockERC20");
    const paymentToken = await MockERC20.deploy("USD Coin", "USDC", 1_000_000);

    const StockToken = await ethers.getContractFactory("StockToken");
    const stockToken = await StockToken.deploy("ACME Corp", "ACME", firm.address, 500_000);

    const DividendVault = await ethers.getContractFactory("DividendVault");
    const vault = await DividendVault.deploy(await policy.getAddress(), await paymentToken.getAddress());

    const vaultAddr = await vault.getAddress();

    await policy.setRecorder(vaultAddr, true);
    await policy.setDividendPolicy(firm.address, true, 1_000, 3_600);
    await stockToken.connect(firm).mint(holderA.address, 100);
    await stockToken.connect(firm).mint(holderB.address, 100);

    await paymentToken.transfer(firm.address, 5_000);
    await paymentToken.connect(firm).approve(vaultAddr, ethers.MaxUint256);

    return { policy, paymentToken, stockToken, vault, owner, firm, holderA, holderB, outsider };
  }

  it("accepts firm reserve deposits", async function () {
    const { paymentToken, vault, firm } = await deploy();

    await expect(vault.connect(firm).deposit(1_500))
      .to.emit(vault, "DividendDeposited")
      .withArgs(firm.address, 1_500);

    expect(await vault.firmReserve(firm.address)).to.equal(1_500);
    expect(await paymentToken.balanceOf(firm.address)).to.equal(5_000 - 1_500);
    expect(await paymentToken.balanceOf(await vault.getAddress())).to.equal(1_500);
  });

  it("distributes dividends and updates reserves and holder balances", async function () {
    const { paymentToken, stockToken, vault, firm, holderA, holderB } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await vault.connect(firm).deposit(1_000);
    await vault.connect(firm).distribute(stockAddr, [holderA.address, holderB.address], [300, 200]);

    expect(await vault.firmReserve(firm.address)).to.equal(500);
    expect(await paymentToken.balanceOf(holderA.address)).to.equal(300);
    expect(await paymentToken.balanceOf(holderB.address)).to.equal(200);
  });

  it("emits DividendPaid for every holder", async function () {
    const { stockToken, vault, firm, holderA, holderB } = await deploy();
    const stockAddr = await stockToken.getAddress();

    await vault.connect(firm).deposit(1_000);

    await expect(vault.connect(firm).distribute(stockAddr, [holderA.address, holderB.address], [300, 200]))
      .to.emit(vault, "DividendPaid")
      .withArgs(firm.address, stockAddr, holderA.address, 300)
      .and.to.emit(vault, "DividendPaid")
      .withArgs(firm.address, stockAddr, holderB.address, 200);
  });

  it("reverts when the payout exceeds the dividend budget", async function () {
    const { stockToken, vault, firm, holderA } = await deploy();

    await vault.connect(firm).deposit(2_000);

    await expect(
      vault.connect(firm).distribute(await stockToken.getAddress(), [holderA.address], [1_001])
    ).to.be.revertedWith("POLICY_DIVIDEND_BUDGET");
  });

  it("reverts when the payout exceeds the firm reserve", async function () {
    const { stockToken, vault, firm, holderA } = await deploy();

    await vault.connect(firm).deposit(300);

    await expect(
      vault.connect(firm).distribute(await stockToken.getAddress(), [holderA.address], [301])
    ).to.be.revertedWith("DIVIDEND_RESERVE_EXCEEDED");
  });

  it("reverts when holder and amount lengths differ", async function () {
    const { stockToken, vault, firm, holderA, holderB } = await deploy();

    await vault.connect(firm).deposit(1_000);

    await expect(
      vault.connect(firm).distribute(await stockToken.getAddress(), [holderA.address, holderB.address], [100])
    ).to.be.revertedWith("DIVIDEND_LENGTH_MISMATCH");
  });

  it("reverts when a dividend recipient does not hold the stock token", async function () {
    const { stockToken, vault, firm, outsider } = await deploy();

    await vault.connect(firm).deposit(1_000);

    await expect(
      vault.connect(firm).distribute(await stockToken.getAddress(), [outsider.address], [100])
    ).to.be.revertedWith("DIVIDEND_HOLDER_NOT_ELIGIBLE");
  });
});
