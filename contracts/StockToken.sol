// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract StockToken is ERC20 {
    address public immutable firm;
    uint256 public immutable maxSupply;

    constructor(
        string memory name_,
        string memory symbol_,
        address firm_,
        uint256 maxSupply_
    ) ERC20(name_, symbol_) {
        require(firm_ != address(0), "TOKEN_ZERO_FIRM");
        require(maxSupply_ > 0, "TOKEN_ZERO_CAP");

        firm = firm_;
        maxSupply = maxSupply_;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == firm, "TOKEN_NOT_FIRM");
        require(totalSupply() + amount <= maxSupply, "TOKEN_CAP_EXCEEDED");

        _mint(to, amount);
    }
}
