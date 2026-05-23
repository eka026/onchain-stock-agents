import { expect } from "chai";
import { ethers } from "hardhat";

describe("LPToken", function () {
  async function deploy() {
    const [owner, pool, other] = await ethers.getSigners();
    const LPToken = await ethers.getContractFactory("LPToken");
    const token: any = await LPToken.deploy("AMM LP Token", "ALP");
    return { token, owner, pool, other };
  }

  it("sets pool via setPool and blocks a second call", async function () {
    const { token, pool } = await deploy();
    await token.setPool(pool.address);
    expect(await token.pool()).to.equal(pool.address);
    await expect(token.setPool(pool.address)).to.be.revertedWith("LPTOKEN_POOL_ALREADY_SET");
  });

  it("rejects zero pool address", async function () {
    const { token } = await deploy();
    await expect(token.setPool(ethers.ZeroAddress)).to.be.revertedWith("LPTOKEN_ZERO_POOL");
  });

  it("allows the pool to mint LP tokens", async function () {
    const { token, pool, other } = await deploy();
    await token.setPool(pool.address);
    await token.connect(pool).mint(other.address, 1_000);
    expect(await token.balanceOf(other.address)).to.equal(1_000);
    expect(await token.totalSupply()).to.equal(1_000);
  });

  it("allows the pool to burn LP tokens", async function () {
    const { token, pool, other } = await deploy();
    await token.setPool(pool.address);
    await token.connect(pool).mint(other.address, 1_000);
    await token.connect(pool).burn(other.address, 400);
    expect(await token.balanceOf(other.address)).to.equal(600);
  });

  it("rejects mint and burn from non-pool addresses", async function () {
    const { token, pool, other } = await deploy();
    await token.setPool(pool.address);
    await expect(token.connect(other).mint(other.address, 1))
      .to.be.revertedWith("LPTOKEN_NOT_POOL");
    await token.connect(pool).mint(other.address, 100);
    await expect(token.connect(other).burn(other.address, 1))
      .to.be.revertedWith("LPTOKEN_NOT_POOL");
  });

  it("rejects mint before pool is set", async function () {
    const { token, other } = await deploy();
    await expect(token.connect(other).mint(other.address, 1))
      .to.be.revertedWith("LPTOKEN_NOT_POOL");
  });
});
