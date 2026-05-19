// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "./AgentPolicy.sol";

interface IFirmStockToken is IERC20 {
    function firm() external view returns (address);
}

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
        uint256 totalAmount
    ) external {
        require(stockToken != address(0), "DIVIDEND_ZERO_STOCK");
        require(totalAmount > 0, "DIVIDEND_ZERO_AMOUNT");

        IFirmStockToken stock = IFirmStockToken(stockToken);
        require(stock.firm() == msg.sender, "DIVIDEND_NOT_TOKEN_FIRM");

        uint256 totalSupply = stock.totalSupply();
        require(totalSupply > 0, "DIVIDEND_ZERO_SUPPLY");

        uint256 paid;
        uint256[] memory payouts = new uint256[](holders.length);
        for (uint256 i = 0; i < holders.length; i++) {
            require(holders[i] != address(0), "DIVIDEND_ZERO_HOLDER");
            for (uint256 j = 0; j < i; j++) {
                require(holders[i] != holders[j], "DIVIDEND_DUPLICATE_HOLDER");
            }

            uint256 holderBalance = stock.balanceOf(holders[i]);
            require(holderBalance > 0, "DIVIDEND_HOLDER_NOT_ELIGIBLE");

            uint256 payout = (totalAmount * holderBalance) / totalSupply;
            payouts[i] = payout;
            paid += payout;
        }

        require(paid == totalAmount, "DIVIDEND_INCOMPLETE_DISTRIBUTION");
        policy.validateDividend(msg.sender, paid);
        require(paid <= firmReserve[msg.sender], "DIVIDEND_RESERVE_EXCEEDED");

        firmReserve[msg.sender] -= paid;
        policy.recordDividend(msg.sender, paid);

        for (uint256 i = 0; i < holders.length; i++) {
            require(paymentToken.transfer(holders[i], payouts[i]), "DIVIDEND_PAYMENT_FAILED");
            emit DividendPaid(msg.sender, stockToken, holders[i], payouts[i]);
        }
    }
}
