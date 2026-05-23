import json

import pytest

from agents.chain import ContractRegistry
from agents.news_feed import Scenario


class FakeCall:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class FakeFunctions:
    def __init__(self, values):
        self.values = values

    def __getattr__(self, name):
        def method(*args):
            key = (name, args)
            if key not in self.values:
                key = name
            return FakeCall(self.values[key])

        return method


class FakeContract:
    def __init__(self, address, abi, values=None):
        self.address = address
        self.abi = abi
        self.functions = FakeFunctions(values or {})


class FakeEth:
    def __init__(self):
        self.contracts = {}

    def contract(self, address, abi):
        contract = FakeContract(address, abi)
        self.contracts[address] = contract
        return contract


class FakeWeb3:
    def __init__(self):
        self.eth = FakeEth()


def write_abis(tmp_path, names=("AgentPolicy", "AMMPool", "LPToken", "FeeVault", "MockERC20")):
    for name in names:
        (tmp_path / f"{name}.json").write_text(json.dumps([{"name": name}]), encoding="utf-8")


def scenario():
    return Scenario(
        seed=1,
        news_file="data/news.json",
        policy_address="0xpolicy",
        min_interval_ticks=1,
        max_interval_ticks=2,
        max_events=1,
        tokens=[
            {"symbol": "USD", "address": "0xusd"},
            {"symbol": "TECH", "address": "0xtech"},
            {"symbol": "FIN", "address": "0xfin"},
        ],
        pools=[
            {
                "id": "TECH-USD",
                "base_symbol": "TECH",
                "quote_symbol": "USD",
                "pool_address": "0xtechpool",
                "lp_token_address": "0xtechlp",
                "vault_address": "0xtechvault",
            },
            {
                "id": "FIN-USD",
                "base_symbol": "FIN",
                "quote_symbol": "USD",
                "pool_address": "0xfinpool",
                "lp_token_address": "0xfinlp",
                "vault_address": "0xfinvault",
            },
        ],
    )


def test_registry_loads_abis_and_builds_contracts(tmp_path):
    write_abis(tmp_path)
    web3 = FakeWeb3()

    registry = ContractRegistry(scenario(), web3=web3, abi_dir=tmp_path)

    assert registry.policy.address == "0xpolicy"
    assert registry.token_address("TECH") == "0xtech"
    assert registry.token_contract("USD").address == "0xusd"
    assert registry.pool_info("TECH-USD").base_symbol == "TECH"
    assert registry.pool_contracts("TECH-USD").pool.address == "0xtechpool"
    assert registry.pool_contracts("TECH-USD").lp_token.address == "0xtechlp"
    assert registry.pool_contracts("TECH-USD").vault.address == "0xtechvault"
    assert registry.pool_contracts("TECH-USD").base_token.address == "0xtech"
    assert registry.pool_contracts("TECH-USD").quote_token.address == "0xusd"


def test_registry_rejects_unknown_token_symbol(tmp_path):
    write_abis(tmp_path)
    registry = ContractRegistry(scenario(), web3=FakeWeb3(), abi_dir=tmp_path)

    with pytest.raises(KeyError, match="unknown token symbol"):
        registry.token_address("MISSING")

    with pytest.raises(KeyError, match="unknown token symbol"):
        registry.token_contract("MISSING")


def test_registry_rejects_unknown_pool_id(tmp_path):
    write_abis(tmp_path)
    registry = ContractRegistry(scenario(), web3=FakeWeb3(), abi_dir=tmp_path)

    with pytest.raises(KeyError, match="unknown pool_id"):
        registry.pool_info("MISSING-USD")

    with pytest.raises(KeyError, match="unknown pool_id"):
        registry.pool_contracts("MISSING-USD")


def test_registry_fails_when_abi_is_missing(tmp_path):
    write_abis(tmp_path, names=("AgentPolicy", "AMMPool", "LPToken", "FeeVault"))

    with pytest.raises(FileNotFoundError, match="MockERC20"):
        ContractRegistry(scenario(), web3=FakeWeb3(), abi_dir=tmp_path)
