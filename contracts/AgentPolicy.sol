// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract AgentPolicy is Ownable {
    struct TraderPolicy {
        bool enabled;
        uint256 maxSwapAmount;
        uint256 spendingLimit;
        uint256 spentAmount;
        uint256 windowStart;
        uint256 windowDuration;
    }

    struct LPPolicy {
        bool enabled;
        uint256 maxLiquidityAdd;     // max per-token amount per addLiquidity call
        uint256 maxLiquidityRemove;  // max LP shares per removeLiquidity call
        uint256 maxFeeWithdrawal;    // max cumulative fee value (tokenA + tokenB) per window
        uint256 withdrawnFees;
        uint256 windowStart;
        uint256 windowDuration;
    }

    mapping(address => bool) public isTokenApproved;
    mapping(address => TraderPolicy) public traderPolicies;
    mapping(address => LPPolicy) public lpPolicies;
    mapping(address => bool) public isRecorder;

    event TokenApprovalSet(address indexed token, bool approved);
    event TraderPolicySet(
        address indexed trader,
        bool enabled,
        uint256 maxSwapAmount,
        uint256 spendingLimit,
        uint256 windowDuration
    );
    event LPPolicySet(
        address indexed lp,
        bool enabled,
        uint256 maxLiquidityAdd,
        uint256 maxLiquidityRemove,
        uint256 maxFeeWithdrawal,
        uint256 windowDuration
    );
    event RecorderSet(address indexed recorder, bool approved);
    event SpendingRecorded(address indexed trader, uint256 amount, uint256 windowStart, uint256 spentAmount);
    event FeeWithdrawalRecorded(address indexed lp, uint256 amount, uint256 windowStart, uint256 withdrawnFees);

    constructor() Ownable(msg.sender) {}

    function setTokenApproval(address token, bool approved) external onlyOwner {
        require(token != address(0), "POLICY_ZERO_TOKEN");
        isTokenApproved[token] = approved;
        emit TokenApprovalSet(token, approved);
    }

    function setTraderPolicy(
        address trader,
        bool enabled,
        uint256 maxSwapAmount,
        uint256 spendingLimit,
        uint256 windowDuration
    ) external onlyOwner {
        require(trader != address(0), "POLICY_ZERO_TRADER");
        TraderPolicy storage tp = traderPolicies[trader];
        tp.enabled = enabled;
        tp.maxSwapAmount = maxSwapAmount;
        tp.spendingLimit = spendingLimit;
        tp.windowDuration = windowDuration;
        if (tp.windowStart == 0) tp.windowStart = block.timestamp;
        emit TraderPolicySet(trader, enabled, maxSwapAmount, spendingLimit, windowDuration);
    }

    function setLPPolicy(
        address lp,
        bool enabled,
        uint256 maxLiquidityAdd,
        uint256 maxLiquidityRemove,
        uint256 maxFeeWithdrawal,
        uint256 windowDuration
    ) external onlyOwner {
        require(lp != address(0), "POLICY_ZERO_LP");
        LPPolicy storage lpp = lpPolicies[lp];
        lpp.enabled = enabled;
        lpp.maxLiquidityAdd = maxLiquidityAdd;
        lpp.maxLiquidityRemove = maxLiquidityRemove;
        lpp.maxFeeWithdrawal = maxFeeWithdrawal;
        lpp.windowDuration = windowDuration;
        if (lpp.windowStart == 0) lpp.windowStart = block.timestamp;
        emit LPPolicySet(lp, enabled, maxLiquidityAdd, maxLiquidityRemove, maxFeeWithdrawal, windowDuration);
    }

    function setRecorder(address recorder, bool approved) external onlyOwner {
        require(recorder != address(0), "POLICY_ZERO_RECORDER");
        isRecorder[recorder] = approved;
        emit RecorderSet(recorder, approved);
    }

    // ── Validation ────────────────────────────────────────────────────────────

    function validateSwap(address trader, address tokenIn, uint256 amountIn) external view {
        require(isTokenApproved[tokenIn], "POLICY_TOKEN_NOT_APPROVED");
        TraderPolicy storage tp = traderPolicies[trader];
        require(tp.enabled, "POLICY_TRADER_DISABLED");
        require(amountIn <= tp.maxSwapAmount, "POLICY_SWAP_TOO_LARGE");
        require(currentSpentAmount(trader) + amountIn <= tp.spendingLimit, "POLICY_SPENDING_LIMIT");
    }

    function validateLiquidityAdd(address lp, uint256 amountA, uint256 amountB) external view {
        LPPolicy storage lpp = lpPolicies[lp];
        require(lpp.enabled, "POLICY_LP_DISABLED");
        require(amountA <= lpp.maxLiquidityAdd, "POLICY_LIQUIDITY_TOO_LARGE");
        require(amountB <= lpp.maxLiquidityAdd, "POLICY_LIQUIDITY_TOO_LARGE");
    }

    function validateLiquidityRemove(address lp, uint256 lpShares) external view {
        LPPolicy storage lpp = lpPolicies[lp];
        require(lpp.enabled, "POLICY_LP_DISABLED");
        require(lpShares <= lpp.maxLiquidityRemove, "POLICY_REMOVE_TOO_LARGE");
    }

    function validateFeeWithdrawal(address lp, uint256 amount) external view {
        LPPolicy storage lpp = lpPolicies[lp];
        require(lpp.enabled, "POLICY_LP_DISABLED");
        require(currentFeeWithdrawn(lp) + amount <= lpp.maxFeeWithdrawal, "POLICY_FEE_WITHDRAWAL_LIMIT");
    }

    // ── Recording ─────────────────────────────────────────────────────────────

    function recordSpending(address trader, uint256 amount) external {
        require(isRecorder[msg.sender], "POLICY_NOT_RECORDER");
        TraderPolicy storage tp = traderPolicies[trader];
        bool expired = _windowExpired(tp.windowStart, tp.windowDuration);
        tp.windowStart = expired ? block.timestamp : tp.windowStart;
        tp.spentAmount = (expired ? 0 : tp.spentAmount) + amount;
        emit SpendingRecorded(trader, amount, tp.windowStart, tp.spentAmount);
    }

    function recordFeeWithdrawal(address lp, uint256 amount) external {
        require(isRecorder[msg.sender], "POLICY_NOT_RECORDER");
        LPPolicy storage lpp = lpPolicies[lp];
        bool expired = _windowExpired(lpp.windowStart, lpp.windowDuration);
        lpp.windowStart = expired ? block.timestamp : lpp.windowStart;
        lpp.withdrawnFees = (expired ? 0 : lpp.withdrawnFees) + amount;
        emit FeeWithdrawalRecorded(lp, amount, lpp.windowStart, lpp.withdrawnFees);
    }

    // ── Views ─────────────────────────────────────────────────────────────────

    function currentSpentAmount(address trader) public view returns (uint256) {
        TraderPolicy storage tp = traderPolicies[trader];
        return _windowExpired(tp.windowStart, tp.windowDuration) ? 0 : tp.spentAmount;
    }

    function currentFeeWithdrawn(address lp) public view returns (uint256) {
        LPPolicy storage lpp = lpPolicies[lp];
        return _windowExpired(lpp.windowStart, lpp.windowDuration) ? 0 : lpp.withdrawnFees;
    }

    function _windowExpired(uint256 windowStart, uint256 windowDuration) private view returns (bool) {
        return windowDuration > 0 && windowStart > 0 && block.timestamp >= windowStart + windowDuration;
    }
}
