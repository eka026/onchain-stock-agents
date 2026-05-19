// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "./AgentPolicy.sol";

contract Exchange {
    AgentPolicy public immutable policy;
    IERC20 public immutable paymentToken;

    mapping(bytes32 => uint256) public openSellOrderCount;
    mapping(bytes32 => uint256) public openBuyOrderCount;

    event SellOrderCreated(
        address indexed seller,
        address indexed stockToken,
        uint256 shareAmount,
        uint256 paymentAmount
    );
    event BuyOrderCreated(
        address indexed buyer,
        address indexed stockToken,
        uint256 shareAmount,
        uint256 paymentAmount
    );
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

    function createSellOrder(address stockToken, uint256 shareAmount, uint256 paymentAmount) external {
        _requirePositiveTrade(shareAmount, paymentAmount);
        policy.validateTrade(msg.sender, stockToken, shareAmount, 0);

        openSellOrderCount[_orderKey(msg.sender, stockToken, shareAmount, paymentAmount)] += 1;

        emit SellOrderCreated(msg.sender, stockToken, shareAmount, paymentAmount);
    }

    function createBuyOrder(address stockToken, uint256 shareAmount, uint256 paymentAmount) external {
        _requirePositiveTrade(shareAmount, paymentAmount);
        policy.validateTrade(msg.sender, stockToken, shareAmount, paymentAmount);

        openBuyOrderCount[_orderKey(msg.sender, stockToken, shareAmount, paymentAmount)] += 1;

        emit BuyOrderCreated(msg.sender, stockToken, shareAmount, paymentAmount);
    }

    function buy(address stockToken, address seller, uint256 shareAmount, uint256 paymentAmount) external {
        _requirePositiveTrade(shareAmount, paymentAmount);
        policy.validateTrade(msg.sender, stockToken, shareAmount, paymentAmount);

        bytes32 orderKey = _orderKey(seller, stockToken, shareAmount, paymentAmount);
        require(openSellOrderCount[orderKey] > 0, "EXCHANGE_SELL_ORDER_NOT_OPEN");
        openSellOrderCount[orderKey] -= 1;

        require(paymentToken.transferFrom(msg.sender, seller, paymentAmount), "EXCHANGE_PAYMENT_FAILED");
        require(IERC20(stockToken).transferFrom(seller, msg.sender, shareAmount), "EXCHANGE_SHARE_FAILED");
        policy.recordSpending(msg.sender, paymentAmount);
        emit TradeSettled(msg.sender, stockToken, seller, shareAmount, paymentAmount, true);
    }

    function sell(address stockToken, address buyer, uint256 shareAmount, uint256 paymentAmount) external {
        _requirePositiveTrade(shareAmount, paymentAmount);
        policy.validateTrade(msg.sender, stockToken, shareAmount, 0);
        policy.validateTrade(buyer, stockToken, shareAmount, paymentAmount);

        bytes32 orderKey = _orderKey(buyer, stockToken, shareAmount, paymentAmount);
        require(openBuyOrderCount[orderKey] > 0, "EXCHANGE_BUY_ORDER_NOT_OPEN");
        openBuyOrderCount[orderKey] -= 1;

        require(IERC20(stockToken).transferFrom(msg.sender, buyer, shareAmount), "EXCHANGE_SHARE_FAILED");
        require(paymentToken.transferFrom(buyer, msg.sender, paymentAmount), "EXCHANGE_PAYMENT_FAILED");
        policy.recordSpending(buyer, paymentAmount);
        emit TradeSettled(msg.sender, stockToken, buyer, shareAmount, paymentAmount, false);
    }

    function _requirePositiveTrade(uint256 shareAmount, uint256 paymentAmount) private pure {
        require(shareAmount > 0, "EXCHANGE_ZERO_SHARES");
        require(paymentAmount > 0, "EXCHANGE_ZERO_PAYMENT");
    }

    function _orderKey(
        address maker,
        address stockToken,
        uint256 shareAmount,
        uint256 paymentAmount
    ) private pure returns (bytes32) {
        return keccak256(abi.encode(maker, stockToken, shareAmount, paymentAmount));
    }
}
