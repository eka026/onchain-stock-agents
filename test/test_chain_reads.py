from agents.chain import ChainReader
from test.test_chain_contracts import FakeContract, FakeWeb3, scenario, write_abis
from agents.chain import ContractRegistry


def registry_with_values(tmp_path):
    write_abis(tmp_path)
    registry = ContractRegistry(scenario(), web3=FakeWeb3(), abi_dir=tmp_path)

    registry.tokens["USD"] = FakeContract(
        "0xusd",
        [],
        {
            ("balanceOf", ("0xalice",)): 1_000,
        },
    )
    registry.tokens["TECH"] = FakeContract(
        "0xtech",
        [],
        {
            ("balanceOf", ("0xalice",)): 25,
        },
    )
    registry.pools["TECH-USD"].lp_token = FakeContract(
        "0xtechlp",
        [],
        {
            ("balanceOf", ("0xalice",)): 50,
            "totalSupply": 1_000,
        },
    )
    registry.pools["TECH-USD"].pool = FakeContract(
        "0xtechpool",
        [],
        {
            "reserveA": 10_000,
            "reserveB": 20_000,
            "spotPrice": 2_000_000_000_000_000_000,
            "feeBps": 30,
        },
    )
    registry.pools["TECH-USD"].vault = FakeContract(
        "0xtechvault",
        [],
        {
            "totalFeesA": 7,
            "totalFeesB": 11,
            "cumulativeFeesA": 70,
            "cumulativeFeesB": 110,
            ("claimableFees", ("0xlp", 50)): (3, 5),
        },
    )
    registry.policy = FakeContract(
        "0xpolicy",
        [],
        {
            ("isTokenApproved", ("0xtech",)): True,
            ("traderPolicies", ("0xtrader",)): (True, 100, 1_000, 25, 123, 3600),
            ("lpPolicies", ("0xlp",)): (True, 500, 300, 50, 10, 123, 3600),
            ("currentSpentAmount", ("0xtrader",)): 20,
            ("currentFeeWithdrawn", ("0xlp",)): 5,
        },
    )

    return registry


def test_chain_reader_reads_token_balances(tmp_path):
    reader = ChainReader(registry_with_values(tmp_path))

    assert reader.token_balance("USD", "0xalice") == 1_000
    assert reader.token_balance("TECH", "0xalice") == 25


def test_chain_reader_reads_lp_balance(tmp_path):
    reader = ChainReader(registry_with_values(tmp_path))

    assert reader.lp_balance("TECH-USD", "0xalice") == 50
    assert reader.lp_total_supply("TECH-USD") == 1_000


def test_chain_reader_reads_reserves_and_spot_price(tmp_path):
    reader = ChainReader(registry_with_values(tmp_path))

    assert reader.reserves("TECH-USD") == (10_000, 20_000)
    assert reader.spot_price("TECH-USD") == 2_000_000_000_000_000_000


def test_chain_reader_reads_vault_fees(tmp_path):
    reader = ChainReader(registry_with_values(tmp_path))

    assert reader.vault_fees("TECH-USD") == (7, 11)
    assert reader.vault_cumulative_fees("TECH-USD") == (70, 110)
    assert reader.claimable_fees("TECH-USD", "0xlp", 50) == (3, 5)
    assert reader.pool_fee_bps("TECH-USD") == 30


def test_chain_reader_reads_policy_state(tmp_path):
    reader = ChainReader(registry_with_values(tmp_path))

    assert reader.is_token_approved("TECH") is True
    assert reader.trader_policy("0xtrader") == (True, 100, 1_000, 25, 123, 3600)
    assert reader.lp_policy("0xlp") == (True, 500, 300, 50, 10, 123, 3600)
    assert reader.current_spent_amount("0xtrader") == 20
    assert reader.current_fee_withdrawn("0xlp") == 5


def test_chain_reader_reads_token_allowance(tmp_path):
    reader = ChainReader(registry_with_values(tmp_path))

    reader.registry.tokens["USD"] = FakeContract(
        "0xusd",
        [],
        {
            ("allowance", ("0xalice", "0xpool")): 123,
        },
    )

    assert reader.token_allowance("USD", "0xalice", "0xpool") == 123


class CountingCall:
    def __init__(self, value, counter, name):
        self.value = value
        self.counter = counter
        self.name = name

    def call(self):
        self.counter[self.name] = self.counter.get(self.name, 0) + 1
        return self.value


class CountingFunctions:
    def __init__(self, values, counter):
        self.values = values
        self.counter = counter

    def __getattr__(self, name):
        def method(*args):
            key = (name, args)
            if key not in self.values:
                key = name
            return CountingCall(self.values[key], self.counter, name)

        return method


class CountingContract:
    def __init__(self, address, values, counter):
        self.address = address
        self.functions = CountingFunctions(values, counter)


def test_chain_reader_cache_reuses_shared_reads_and_resets(tmp_path):
    registry = registry_with_values(tmp_path)
    counter = {}
    registry.pools["TECH-USD"].pool = CountingContract(
        "0xtechpool",
        {
            "reserveA": 10_000,
            "reserveB": 20_000,
            "spotPrice": 2_000_000_000_000_000_000,
            "feeBps": 30,
        },
        counter,
    )
    registry.pools["TECH-USD"].vault = CountingContract(
        "0xtechvault",
        {
            "totalFeesA": 7,
            "totalFeesB": 11,
            "cumulativeFeesA": 70,
            "cumulativeFeesB": 110,
            ("claimableFees", ("0xlp", 50)): (3, 5),
        },
        counter,
    )
    registry.policy = CountingContract(
        "0xpolicy",
        {
            ("isTokenApproved", ("0xtech",)): True,
        },
        counter,
    )
    reader = ChainReader(registry)

    reader.enable_cache()
    assert reader.reserves("TECH-USD") == (10_000, 20_000)
    assert reader.reserves("TECH-USD") == (10_000, 20_000)
    assert reader.spot_price("TECH-USD") == 2_000_000_000_000_000_000
    assert reader.spot_price("TECH-USD") == 2_000_000_000_000_000_000
    assert reader.vault_fees("TECH-USD") == (7, 11)
    assert reader.vault_fees("TECH-USD") == (7, 11)
    assert reader.vault_cumulative_fees("TECH-USD") == (70, 110)
    assert reader.vault_cumulative_fees("TECH-USD") == (70, 110)
    assert reader.claimable_fees("TECH-USD", "0xlp", 50) == (3, 5)
    assert reader.claimable_fees("TECH-USD", "0xlp", 50) == (3, 5)
    assert reader.pool_fee_bps("TECH-USD") == 30
    assert reader.pool_fee_bps("TECH-USD") == 30
    assert reader.is_token_approved("TECH") is True
    assert reader.is_token_approved("TECH") is True

    assert counter == {
        "reserveA": 1,
        "reserveB": 1,
        "spotPrice": 1,
        "totalFeesA": 1,
        "totalFeesB": 1,
        "cumulativeFeesA": 1,
        "cumulativeFeesB": 1,
        "claimableFees": 1,
        "feeBps": 1,
        "isTokenApproved": 1,
    }

    reader.reset_cache()
    assert reader.spot_price("TECH-USD") == 2_000_000_000_000_000_000
    assert reader.spot_price("TECH-USD") == 2_000_000_000_000_000_000

    assert counter["spotPrice"] == 3
