// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "./AgentPolicy.sol";

contract Exchange {
    AgentPolicy public immutable policy;
    IERC20 public immutable paymentToken;

    event TradeSettled(
        address indexed trader,
        address indexed stockToken,
        address indexed counterparty,
        uint256 shareAmount,
        uint256 paymentAmount,
        bool isBuy
    );

    constructor(AgentPolicy policy_, IERC20 paymentToken_) {
        require(address(policy_) != address(0), "EXCHANGE_ZERO_POLICY");
        require(address(paymentToken_) != address(0), "EXCHANGE_ZERO_PAYMENT");
        policy = policy_;
        paymentToken = paymentToken_;
    }

    function buy(address stockToken, address seller, uint256 shareAmount, uint256 paymentAmount) external {
        policy.validateTrade(msg.sender, stockToken, shareAmount, paymentAmount);
        require(paymentToken.transferFrom(msg.sender, seller, paymentAmount), "EXCHANGE_PAYMENT_FAILED");
        require(IERC20(stockToken).transferFrom(seller, msg.sender, shareAmount), "EXCHANGE_SHARE_FAILED");
        policy.recordSpending(msg.sender, paymentAmount);
        emit TradeSettled(msg.sender, stockToken, seller, shareAmount, paymentAmount, true);
    }

    function sell(address stockToken, address buyer, uint256 shareAmount, uint256 paymentAmount) external {
        policy.validateTrade(msg.sender, stockToken, shareAmount, 0);
        require(IERC20(stockToken).transferFrom(msg.sender, buyer, shareAmount), "EXCHANGE_SHARE_FAILED");
        require(paymentToken.transferFrom(buyer, msg.sender, paymentAmount), "EXCHANGE_PAYMENT_FAILED");
        emit TradeSettled(msg.sender, stockToken, buyer, shareAmount, paymentAmount, false);
    }
}
