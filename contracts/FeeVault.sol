// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "./AgentPolicy.sol";

contract FeeVault is Ownable {
    AgentPolicy public immutable policy;
    IERC20 public immutable tokenA;
    IERC20 public immutable tokenB;
    IERC20 public immutable lpToken;

    address public pool;

    uint256 public totalFeesA;
    uint256 public totalFeesB;

    event PoolSet(address indexed pool);
    event FeeNotified(address indexed token, uint256 amount);
    event FeesCollected(address indexed lp, uint256 feesA, uint256 feesB);

    constructor(
        AgentPolicy policy_,
        IERC20 tokenA_,
        IERC20 tokenB_,
        IERC20 lpToken_
    ) Ownable(msg.sender) {
        require(address(policy_) != address(0), "FEEVAULT_ZERO_POLICY");
        require(address(tokenA_) != address(0), "FEEVAULT_ZERO_TOKEN_A");
        require(address(tokenB_) != address(0), "FEEVAULT_ZERO_TOKEN_B");
        require(address(lpToken_) != address(0), "FEEVAULT_ZERO_LP_TOKEN");
        policy = policy_;
        tokenA = tokenA_;
        tokenB = tokenB_;
        lpToken = lpToken_;
    }

    function setPool(address pool_) external onlyOwner {
        require(pool == address(0), "FEEVAULT_POOL_ALREADY_SET");
        require(pool_ != address(0), "FEEVAULT_ZERO_POOL");
        pool = pool_;
        emit PoolSet(pool_);
    }

    // Called by AMMPool after transferring fee tokens to this contract
    function notifyFee(address token, uint256 amount) external {
        require(msg.sender == pool, "FEEVAULT_NOT_POOL");
        require(token == address(tokenA) || token == address(tokenB), "FEEVAULT_INVALID_TOKEN");
        if (token == address(tokenA)) {
            totalFeesA += amount;
        } else {
            totalFeesB += amount;
        }
        emit FeeNotified(token, amount);
    }

    // LP claims a proportional share of accumulated fees without burning LP tokens
    function collectFees(uint256 lpShares) external {
        require(lpShares > 0, "FEEVAULT_ZERO_SHARES");
        require(lpToken.balanceOf(msg.sender) >= lpShares, "FEEVAULT_INSUFFICIENT_SHARES");

        uint256 totalSupply = lpToken.totalSupply();
        require(totalSupply > 0, "FEEVAULT_ZERO_SUPPLY");

        uint256 feesA = totalFeesA * lpShares / totalSupply;
        uint256 feesB = totalFeesB * lpShares / totalSupply;
        require(feesA > 0 || feesB > 0, "FEEVAULT_ZERO_FEES");

        policy.validateFeeWithdrawal(msg.sender, feesA + feesB);

        if (feesA > 0) totalFeesA -= feesA;
        if (feesB > 0) totalFeesB -= feesB;

        if (feesA > 0) require(tokenA.transfer(msg.sender, feesA), "FEEVAULT_TRANSFER_A_FAILED");
        if (feesB > 0) require(tokenB.transfer(msg.sender, feesB), "FEEVAULT_TRANSFER_B_FAILED");

        policy.recordFeeWithdrawal(msg.sender, feesA + feesB);
        emit FeesCollected(msg.sender, feesA, feesB);
    }
}
