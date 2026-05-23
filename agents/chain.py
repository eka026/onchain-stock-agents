import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web3 import Web3

from agents.news_feed import PoolInfo, Scenario


DEFAULT_ABI_DIR = Path(__file__).resolve().parent / "abis"


@dataclass
class PoolContracts:
    info: PoolInfo
    pool: Any
    lp_token: Any
    vault: Any
    base_token: Any
    quote_token: Any


class ContractRegistry:
    def __init__(self, scenario: Scenario, web3: Any, abi_dir: str | Path = DEFAULT_ABI_DIR):
        self.scenario = scenario
        self.web3 = web3
        self.abi_dir = Path(abi_dir)
        self.abis = {
            "AgentPolicy": self._load_abi("AgentPolicy"),
            "AMMPool": self._load_abi("AMMPool"),
            "LPToken": self._load_abi("LPToken"),
            "FeeVault": self._load_abi("FeeVault"),
            "MockERC20": self._load_abi("MockERC20"),
        }
        self.tokens_by_symbol = {token.symbol: token.address for token in scenario.tokens}
        self.pools_by_id = {pool.id: pool for pool in scenario.pools}

        self.policy = self._contract(scenario.policy_address, "AgentPolicy")
        self.tokens = {
            symbol: self._contract(address, "MockERC20")
            for symbol, address in self.tokens_by_symbol.items()
        }
        self.pools = {
            pool_id: PoolContracts(
                info=pool,
                pool=self._contract(pool.pool_address, "AMMPool"),
                lp_token=self._contract(pool.lp_token_address, "LPToken"),
                vault=self._contract(pool.vault_address, "FeeVault"),
                base_token=self.token_contract(pool.base_symbol),
                quote_token=self.token_contract(pool.quote_symbol),
            )
            for pool_id, pool in self.pools_by_id.items()
        }

    @classmethod
    def from_rpc(cls, scenario: Scenario, rpc_url: str, abi_dir: str | Path = DEFAULT_ABI_DIR) -> "ContractRegistry":
        return cls(scenario=scenario, web3=Web3(Web3.HTTPProvider(rpc_url)), abi_dir=abi_dir)

    def token_address(self, symbol: str) -> str:
        try:
            return self.tokens_by_symbol[symbol]
        except KeyError as exc:
            raise KeyError(f"unknown token symbol: {symbol}") from exc

    def token_contract(self, symbol: str) -> Any:
        try:
            return self.tokens[symbol]
        except KeyError as exc:
            raise KeyError(f"unknown token symbol: {symbol}") from exc

    def pool_info(self, pool_id: str) -> PoolInfo:
        try:
            return self.pools_by_id[pool_id]
        except KeyError as exc:
            raise KeyError(f"unknown pool_id: {pool_id}") from exc

    def pool_contracts(self, pool_id: str) -> PoolContracts:
        try:
            return self.pools[pool_id]
        except KeyError as exc:
            raise KeyError(f"unknown pool_id: {pool_id}") from exc

    def _load_abi(self, contract_name: str) -> list[dict[str, Any]]:
        path = self.abi_dir / f"{contract_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"missing ABI file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _contract(self, address: str, contract_name: str) -> Any:
        if not address:
            raise ValueError(f"missing address for {contract_name}")
        return self.web3.eth.contract(address=address, abi=self.abis[contract_name])


class ChainReader:
    def __init__(self, registry: ContractRegistry):
        self.registry = registry

    def token_balance(self, symbol: str, account: str) -> int:
        return self.registry.token_contract(symbol).functions.balanceOf(account).call()

    def lp_balance(self, pool_id: str, account: str) -> int:
        return self.registry.pool_contracts(pool_id).lp_token.functions.balanceOf(account).call()

    def reserves(self, pool_id: str) -> tuple[int, int]:
        pool = self.registry.pool_contracts(pool_id).pool
        return (
            pool.functions.reserveA().call(),
            pool.functions.reserveB().call(),
        )

    def spot_price(self, pool_id: str) -> int:
        return self.registry.pool_contracts(pool_id).pool.functions.spotPrice().call()

    def vault_fees(self, pool_id: str) -> tuple[int, int]:
        vault = self.registry.pool_contracts(pool_id).vault
        return (
            vault.functions.totalFeesA().call(),
            vault.functions.totalFeesB().call(),
        )

    def is_token_approved(self, symbol: str) -> bool:
        address = self.registry.token_address(symbol)
        return self.registry.policy.functions.isTokenApproved(address).call()

    def trader_policy(self, trader: str) -> Any:
        return self.registry.policy.functions.traderPolicies(trader).call()

    def lp_policy(self, lp: str) -> Any:
        return self.registry.policy.functions.lpPolicies(lp).call()
