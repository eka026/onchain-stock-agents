// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "./AgentPolicy.sol";

contract DividendVault {
    AgentPolicy public immutable policy;
    IERC20 public immutable paymentToken;

    mapping(address => uint256) public firmReserve;

    event DividendDeposited(address indexed firm, uint256 amount);
    event DividendPaid(
        address indexed firm,
        address indexed stockToken,
        address indexed holder,
        uint256 amount
    );

    constructor(AgentPolicy policy_, IERC20 paymentToken_) {
        require(address(policy_) != address(0), "DIVIDEND_ZERO_POLICY");
        require(address(paymentToken_) != address(0), "DIVIDEND_ZERO_PAYMENT");

        policy = policy_;
        paymentToken = paymentToken_;
    }

    function deposit(uint256 amount) external {
        require(paymentToken.transferFrom(msg.sender, address(this), amount), "DIVIDEND_DEPOSIT_FAILED");
        firmReserve[msg.sender] += amount;

        emit DividendDeposited(msg.sender, amount);
    }

    function distribute(
        address stockToken,
        address[] calldata holders,
        uint256[] calldata amounts
    ) external {
        require(holders.length == amounts.length, "DIVIDEND_LENGTH_MISMATCH");

        uint256 total;
        for (uint256 i = 0; i < amounts.length; i++) {
            total += amounts[i];
        }

        policy.validateDividend(msg.sender, total);
        require(total <= firmReserve[msg.sender], "DIVIDEND_RESERVE_EXCEEDED");

        firmReserve[msg.sender] -= total;
        policy.recordDividend(msg.sender, total);

        for (uint256 i = 0; i < holders.length; i++) {
            require(paymentToken.transfer(holders[i], amounts[i]), "DIVIDEND_PAYMENT_FAILED");
            emit DividendPaid(msg.sender, stockToken, holders[i], amounts[i]);
        }
    }
}
