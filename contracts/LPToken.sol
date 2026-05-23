// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract LPToken is ERC20, Ownable {
    address public pool;

    event PoolSet(address indexed pool);

    constructor(string memory name_, string memory symbol_) ERC20(name_, symbol_) Ownable(msg.sender) {}

    function setPool(address pool_) external onlyOwner {
        require(pool == address(0), "LPTOKEN_POOL_ALREADY_SET");
        require(pool_ != address(0), "LPTOKEN_ZERO_POOL");
        pool = pool_;
        emit PoolSet(pool_);
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == pool, "LPTOKEN_NOT_POOL");
        _mint(to, amount);
    }

    function burn(address from, uint256 amount) external {
        require(msg.sender == pool, "LPTOKEN_NOT_POOL");
        _burn(from, amount);
    }
}
