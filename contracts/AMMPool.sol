// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "./AgentPolicy.sol";
import "./LPToken.sol";

interface IFeeVault {
    function notifyFee(address token, uint256 amount) external;
}

contract AMMPool is Ownable {
    AgentPolicy public immutable policy;
    IERC20 public immutable tokenA;
    IERC20 public immutable tokenB;
    LPToken public immutable lpToken;
    IFeeVault public immutable feeVault;

    uint256 public reserveA;
    uint256 public reserveB;
    uint256 public feeBps = 30; // 0.30% default

    event LiquidityAdded(address indexed provider, uint256 amountA, uint256 amountB, uint256 lpShares);
    event LiquidityRemoved(address indexed provider, uint256 amountA, uint256 amountB, uint256 lpShares);
    event Swap(address indexed trader, address indexed tokenIn, uint256 amountIn, uint256 amountOut);
    event FeeBpsUpdated(uint256 newFeeBps);

    constructor(
        AgentPolicy policy_,
        IERC20 tokenA_,
        IERC20 tokenB_,
        LPToken lpToken_,
        IFeeVault feeVault_
    ) Ownable(msg.sender) {
        require(address(policy_) != address(0), "POOL_ZERO_POLICY");
        require(address(tokenA_) != address(0), "POOL_ZERO_TOKEN_A");
        require(address(tokenB_) != address(0), "POOL_ZERO_TOKEN_B");
        require(address(tokenA_) != address(tokenB_), "POOL_SAME_TOKENS");
        require(address(lpToken_) != address(0), "POOL_ZERO_LP_TOKEN");
        require(address(feeVault_) != address(0), "POOL_ZERO_FEE_VAULT");
        policy = policy_;
        tokenA = tokenA_;
        tokenB = tokenB_;
        lpToken = lpToken_;
        feeVault = feeVault_;
    }

    function setFeeBps(uint256 newFeeBps) external onlyOwner {
        require(newFeeBps <= 1_000, "POOL_FEE_TOO_HIGH");
        feeBps = newFeeBps;
        emit FeeBpsUpdated(newFeeBps);
    }

    function addLiquidity(uint256 amountA, uint256 amountB) external returns (uint256 lpShares) {
        require(amountA > 0 && amountB > 0, "POOL_ZERO_AMOUNT");
        policy.validateLiquidityAdd(msg.sender, amountA, amountB);

        uint256 totalSupply = lpToken.totalSupply();
        if (totalSupply == 0) {
            lpShares = _sqrt(amountA * amountB);
        } else {
            uint256 sharesA = amountA * totalSupply / reserveA;
            uint256 sharesB = amountB * totalSupply / reserveB;
            lpShares = sharesA < sharesB ? sharesA : sharesB;
        }
        require(lpShares > 0, "POOL_ZERO_SHARES");

        require(tokenA.transferFrom(msg.sender, address(this), amountA), "POOL_TRANSFER_A_FAILED");
        require(tokenB.transferFrom(msg.sender, address(this), amountB), "POOL_TRANSFER_B_FAILED");

        reserveA += amountA;
        reserveB += amountB;
        lpToken.mint(msg.sender, lpShares);

        emit LiquidityAdded(msg.sender, amountA, amountB, lpShares);
    }

    function removeLiquidity(uint256 lpShares) external returns (uint256 amountA, uint256 amountB) {
        require(lpShares > 0, "POOL_ZERO_SHARES");
        policy.validateLiquidityRemove(msg.sender, lpShares);

        uint256 totalSupply = lpToken.totalSupply();
        amountA = lpShares * reserveA / totalSupply;
        amountB = lpShares * reserveB / totalSupply;
        require(amountA > 0 && amountB > 0, "POOL_ZERO_OUTPUT");

        lpToken.burn(msg.sender, lpShares);
        reserveA -= amountA;
        reserveB -= amountB;

        require(tokenA.transfer(msg.sender, amountA), "POOL_TRANSFER_A_FAILED");
        require(tokenB.transfer(msg.sender, amountB), "POOL_TRANSFER_B_FAILED");

        emit LiquidityRemoved(msg.sender, amountA, amountB, lpShares);
    }

    function swap(address tokenIn, uint256 amountIn) external returns (uint256 amountOut) {
        require(tokenIn == address(tokenA) || tokenIn == address(tokenB), "POOL_INVALID_TOKEN");
        require(amountIn > 0, "POOL_ZERO_INPUT");
        policy.validateSwap(msg.sender, tokenIn, amountIn);

        bool aForB = tokenIn == address(tokenA);
        uint256 reserveIn  = aForB ? reserveA : reserveB;
        uint256 reserveOut = aForB ? reserveB : reserveA;

        uint256 fee = amountIn * feeBps / 10_000;
        uint256 amountInLessFee = amountIn - fee;
        amountOut = reserveOut * amountInLessFee / (reserveIn + amountInLessFee);

        require(amountOut > 0, "POOL_ZERO_OUTPUT");
        require(amountOut < reserveOut, "POOL_INSUFFICIENT_LIQUIDITY");

        require(IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn), "POOL_INPUT_TRANSFER_FAILED");

        if (fee > 0) {
            require(IERC20(tokenIn).transfer(address(feeVault), fee), "POOL_FEE_TRANSFER_FAILED");
            feeVault.notifyFee(tokenIn, fee);
        }

        if (aForB) {
            reserveA += amountInLessFee;
            reserveB -= amountOut;
            require(tokenB.transfer(msg.sender, amountOut), "POOL_OUTPUT_TRANSFER_FAILED");
        } else {
            reserveB += amountInLessFee;
            reserveA -= amountOut;
            require(tokenA.transfer(msg.sender, amountOut), "POOL_OUTPUT_TRANSFER_FAILED");
        }

        policy.recordSpending(msg.sender, amountIn);
        emit Swap(msg.sender, tokenIn, amountIn, amountOut);
    }

    // Price of tokenA denominated in tokenB, scaled by 1e18
    function spotPrice() external view returns (uint256) {
        require(reserveA > 0, "POOL_NO_LIQUIDITY");
        return reserveB * 1e18 / reserveA;
    }

    function _sqrt(uint256 x) private pure returns (uint256 y) {
        if (x == 0) return 0;
        uint256 z = (x + 1) / 2;
        y = x;
        while (z < y) {
            y = z;
            z = (x / z + z) / 2;
        }
    }
}
