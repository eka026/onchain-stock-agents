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
