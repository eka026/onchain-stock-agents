import { expect } from "chai";
import { ethers } from "hardhat";

describe("StockToken", function () {
  async function deployToken() {
    const [firm, holder, outsider] = await ethers.getSigners();
    const StockToken = await ethers.getContractFactory("StockToken");
    const token = await StockToken.deploy("Acme Stock", "ACME", firm.address, 1_000);

    return { token, firm, holder, outsider };
  }

  it("allows the firm to mint shares up to the supply cap", async function () {
    const { token, firm, holder } = await deployToken();

    await expect(token.connect(firm).mint(holder.address, 500))
      .to.emit(token, "Transfer")
      .withArgs(ethers.ZeroAddress, holder.address, 500);

    expect(await token.balanceOf(holder.address)).to.equal(500);
    expect(await token.totalSupply()).to.equal(500);
    expect(await token.maxSupply()).to.equal(1_000);
  });

  it("rejects minting by non-firm accounts", async function () {
    const { token, holder, outsider } = await deployToken();

    await expect(token.connect(outsider).mint(holder.address, 1)).to.be.revertedWith("TOKEN_NOT_FIRM");
  });

  it("rejects minting above the supply cap", async function () {
    const { token, firm, holder } = await deployToken();

    await token.connect(firm).mint(holder.address, 1_000);
    await expect(token.connect(firm).mint(holder.address, 1)).to.be.revertedWith("TOKEN_CAP_EXCEEDED");
  });

  it("rejects invalid constructor arguments", async function () {
    const [firm] = await ethers.getSigners();
    const StockToken = await ethers.getContractFactory("StockToken");

    await expect(StockToken.deploy("Bad Stock", "BAD", ethers.ZeroAddress, 1)).to.be.revertedWith(
      "TOKEN_ZERO_FIRM"
    );
    await expect(StockToken.deploy("Bad Stock", "BAD", firm.address, 0)).to.be.revertedWith(
      "TOKEN_ZERO_CAP"
    );
  });
});
