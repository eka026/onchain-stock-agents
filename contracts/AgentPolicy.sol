// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract AgentPolicy is Ownable {
    struct TraderPolicy {
        bool enabled;
        uint256 maxTradeSize;
        uint256 spendingLimit;
        uint256 spentAmount;
        uint256 windowStart;
        uint256 windowDuration;
    }

    struct DividendPolicy {
        bool enabled;
        uint256 budget;
        uint256 paidAmount;
        uint256 windowStart;
        uint256 windowDuration;
    }

    mapping(address => bool) public isTokenApproved;
    mapping(address => uint256) public tokenMaxTradeSize;
    mapping(address => bool) public isTokenTradingPaused;
    mapping(address => TraderPolicy) public traderPolicies;
    mapping(address => DividendPolicy) public dividendPolicies;
    mapping(address => bool) public isRecorder;

    event TokenPolicySet(address indexed token, bool approved, uint256 maxTradeSize, bool paused);
    event TraderPolicySet(
        address indexed trader,
        bool enabled,
        uint256 maxTradeSize,
        uint256 spendingLimit,
        uint256 windowDuration
    );
    event DividendPolicySet(address indexed firm, bool enabled, uint256 budget, uint256 windowDuration);
    event RecorderSet(address indexed recorder, bool approved);
    event SpendingRecorded(address indexed trader, uint256 amount, uint256 windowStart, uint256 spentAmount);
    event DividendRecorded(address indexed firm, uint256 amount, uint256 windowStart, uint256 paidAmount);

    constructor() Ownable(msg.sender) {}

    function setTokenPolicy(address token, bool approved, uint256 maxTradeSize, bool paused) external onlyOwner {
        require(token != address(0), "POLICY_ZERO_TOKEN");

        isTokenApproved[token] = approved;
        tokenMaxTradeSize[token] = maxTradeSize;
        isTokenTradingPaused[token] = paused;

        emit TokenPolicySet(token, approved, maxTradeSize, paused);
    }

    function setTraderPolicy(
        address trader,
        bool enabled,
        uint256 maxTradeSize,
        uint256 spendingLimit,
        uint256 windowDuration
    ) external onlyOwner {
        require(trader != address(0), "POLICY_ZERO_TRADER");

        TraderPolicy storage policy = traderPolicies[trader];
        policy.enabled = enabled;
        policy.maxTradeSize = maxTradeSize;
        policy.spendingLimit = spendingLimit;
        policy.windowDuration = windowDuration;
        if (policy.windowStart == 0) {
            policy.windowStart = block.timestamp;
        }

        emit TraderPolicySet(trader, enabled, maxTradeSize, spendingLimit, windowDuration);
    }

    function setDividendPolicy(
        address firm,
        bool enabled,
        uint256 budget,
        uint256 windowDuration
    ) external onlyOwner {
        require(firm != address(0), "POLICY_ZERO_FIRM");

        DividendPolicy storage policy = dividendPolicies[firm];
        policy.enabled = enabled;
        policy.budget = budget;
        policy.windowDuration = windowDuration;
        if (policy.windowStart == 0) {
            policy.windowStart = block.timestamp;
        }

        emit DividendPolicySet(firm, enabled, budget, windowDuration);
    }

    function setRecorder(address recorder, bool approved) external onlyOwner {
        require(recorder != address(0), "POLICY_ZERO_RECORDER");

        isRecorder[recorder] = approved;

        emit RecorderSet(recorder, approved);
    }

    function validateTrade(
        address trader,
        address token,
        uint256 shareAmount,
        uint256 paymentAmount
    ) external view {
        require(isTokenApproved[token], "POLICY_TOKEN_NOT_APPROVED");
        require(!isTokenTradingPaused[token], "POLICY_TOKEN_PAUSED");

        TraderPolicy storage traderPolicy = traderPolicies[trader];
        require(traderPolicy.enabled, "POLICY_TRADER_DISABLED");
        require(shareAmount <= traderPolicy.maxTradeSize, "POLICY_TRADE_TOO_LARGE");

        uint256 maxTokenTradeSize = tokenMaxTradeSize[token];
        if (maxTokenTradeSize > 0) {
            require(shareAmount <= maxTokenTradeSize, "POLICY_TOKEN_TRADE_TOO_LARGE");
        }

        require(
            currentSpentAmount(trader) + paymentAmount <= traderPolicy.spendingLimit,
            "POLICY_SPENDING_LIMIT"
        );
    }

    function recordSpending(address trader, uint256 amount) external {
        require(isRecorder[msg.sender], "POLICY_NOT_RECORDER");

        TraderPolicy storage policy = traderPolicies[trader];
        uint256 effectiveSpent = _windowExpired(policy.windowStart, policy.windowDuration)
            ? 0
            : policy.spentAmount;
        uint256 effectiveWindowStart = _windowExpired(policy.windowStart, policy.windowDuration)
            ? block.timestamp
            : policy.windowStart;

        policy.windowStart = effectiveWindowStart;
        policy.spentAmount = effectiveSpent + amount;

        emit SpendingRecorded(trader, amount, policy.windowStart, policy.spentAmount);
    }

    function validateDividend(address firm, uint256 amount) external view {
        DividendPolicy storage policy = dividendPolicies[firm];
        require(policy.enabled, "POLICY_DIVIDEND_DISABLED");
        require(currentDividendPaid(firm) + amount <= policy.budget, "POLICY_DIVIDEND_BUDGET");
    }

    function recordDividend(address firm, uint256 amount) external {
        require(isRecorder[msg.sender], "POLICY_NOT_RECORDER");

        DividendPolicy storage policy = dividendPolicies[firm];
        uint256 effectivePaid = _windowExpired(policy.windowStart, policy.windowDuration) ? 0 : policy.paidAmount;
        uint256 effectiveWindowStart = _windowExpired(policy.windowStart, policy.windowDuration)
            ? block.timestamp
            : policy.windowStart;

        policy.windowStart = effectiveWindowStart;
        policy.paidAmount = effectivePaid + amount;

        emit DividendRecorded(firm, amount, policy.windowStart, policy.paidAmount);
    }

    function currentSpentAmount(address trader) public view returns (uint256) {
        TraderPolicy storage policy = traderPolicies[trader];
        if (_windowExpired(policy.windowStart, policy.windowDuration)) {
            return 0;
        }
        return policy.spentAmount;
    }

    function currentDividendPaid(address firm) public view returns (uint256) {
        DividendPolicy storage policy = dividendPolicies[firm];
        if (_windowExpired(policy.windowStart, policy.windowDuration)) {
            return 0;
        }
        return policy.paidAmount;
    }

    function _windowExpired(uint256 windowStart, uint256 windowDuration) private view returns (bool) {
        return windowDuration > 0 && windowStart > 0 && block.timestamp >= windowStart + windowDuration;
    }
}
