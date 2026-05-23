from agents.chain import ChainReader, ContractRegistry, LocalValidator
from agents.schemas import LPDecision, TraderDecision
from test.test_chain_contracts import FakeContract, FakeWeb3, scenario, write_abis


def validator_with_values(
    tmp_path,
    *,
    trader_policy=(True, 100, 1_000, 25, 123, 3600),
    lp_policy=(True, 500, 300, 50, 10, 123, 3600),
    approved=True,
    tech_allowance=1_000,
    usd_allowance=1_000,
    vault_fees=(7, 11),
):
    write_abis(tmp_path)
    registry = ContractRegistry(scenario(), web3=FakeWeb3(), abi_dir=tmp_path)
    registry.tokens["TECH"] = FakeContract(
        "0xtech",
        [],
        {
            ("allowance", ("0xtrader", "0xtechpool")): tech_allowance,
            ("allowance", ("0xlp", "0xtechpool")): tech_allowance,
        },
    )
    registry.tokens["USD"] = FakeContract(
        "0xusd",
        [],
        {
            ("allowance", ("0xtrader", "0xtechpool")): usd_allowance,
            ("allowance", ("0xlp", "0xtechpool")): usd_allowance,
        },
    )
    registry.pools["TECH-USD"].vault = FakeContract(
        "0xtechvault",
        [],
        {
            "totalFeesA": vault_fees[0],
            "totalFeesB": vault_fees[1],
        },
    )
    registry.policy = FakeContract(
        "0xpolicy",
        [],
        {
            ("isTokenApproved", ("0xtech",)): approved,
            ("isTokenApproved", ("0xusd",)): approved,
            ("traderPolicies", ("0xtrader",)): trader_policy,
            ("lpPolicies", ("0xlp",)): lp_policy,
        },
    )
    return LocalValidator(ChainReader(registry))


def test_trader_validation_accepts_valid_swap(tmp_path):
    validator = validator_with_values(tmp_path)

    result = validator.validate_trader_decision(
        "0xtrader",
        TraderDecision(action="SWAP", pool_id="TECH-USD", token_in="USD", amount_in=100, reason="valid"),
    )

    assert result.ok is True
    assert result.reason is None


def test_trader_validation_rejects_unknown_pool(tmp_path):
    validator = validator_with_values(tmp_path)

    result = validator.validate_trader_decision(
        "0xtrader",
        TraderDecision(action="SWAP", pool_id="MISSING-USD", token_in="USD", amount_in=100, reason="bad"),
    )

    assert result.ok is False
    assert "unknown pool_id" in result.reason


def test_trader_validation_rejects_token_not_in_pool(tmp_path):
    validator = validator_with_values(tmp_path)

    result = validator.validate_trader_decision(
        "0xtrader",
        TraderDecision(action="SWAP", pool_id="TECH-USD", token_in="FIN", amount_in=100, reason="bad"),
    )

    assert result.ok is False
    assert "token_in must be one of" in result.reason


def test_trader_validation_rejects_missing_allowance(tmp_path):
    validator = validator_with_values(tmp_path, usd_allowance=99)

    result = validator.validate_trader_decision(
        "0xtrader",
        TraderDecision(action="SWAP", pool_id="TECH-USD", token_in="USD", amount_in=100, reason="bad"),
    )

    assert result.ok is False
    assert result.reason == "insufficient token allowance"


def test_trader_validation_rejects_policy_violations(tmp_path):
    disabled = validator_with_values(tmp_path, trader_policy=(False, 100, 1_000, 25, 123, 3600))
    too_large = validator_with_values(tmp_path, trader_policy=(True, 99, 1_000, 25, 123, 3600))
    too_expensive = validator_with_values(tmp_path, trader_policy=(True, 100, 124, 25, 123, 3600))

    decision = TraderDecision(action="SWAP", pool_id="TECH-USD", token_in="USD", amount_in=100, reason="bad")

    assert disabled.validate_trader_decision("0xtrader", decision).reason == "trader policy is disabled"
    assert too_large.validate_trader_decision("0xtrader", decision).reason == "swap exceeds max swap amount"
    assert too_expensive.validate_trader_decision("0xtrader", decision).reason == "swap exceeds spending limit"


def test_lp_validation_accepts_valid_add_remove_and_collect(tmp_path):
    validator = validator_with_values(tmp_path)

    add = validator.validate_lp_decision(
        "0xlp",
        LPDecision(
            action="ADD_LIQUIDITY",
            pool_id="TECH-USD",
            amount_a=100,
            amount_b=200,
            reason="valid",
        ),
    )
    remove = validator.validate_lp_decision(
        "0xlp",
        LPDecision(action="REMOVE_LIQUIDITY", pool_id="TECH-USD", lp_shares=100, reason="valid"),
    )
    collect = validator.validate_lp_decision(
        "0xlp",
        LPDecision(action="COLLECT_FEES", pool_id="TECH-USD", lp_shares=100, reason="valid"),
    )

    assert add.ok is True
    assert remove.ok is True
    assert collect.ok is True


def test_lp_validation_rejects_unknown_pool(tmp_path):
    validator = validator_with_values(tmp_path)

    result = validator.validate_lp_decision(
        "0xlp",
        LPDecision(action="COLLECT_FEES", pool_id="MISSING-USD", lp_shares=100, reason="bad"),
    )

    assert result.ok is False
    assert "unknown pool_id" in result.reason


def test_lp_validation_rejects_disabled_policy(tmp_path):
    validator = validator_with_values(tmp_path, lp_policy=(False, 500, 300, 50, 10, 123, 3600))

    result = validator.validate_lp_decision(
        "0xlp",
        LPDecision(action="REMOVE_LIQUIDITY", pool_id="TECH-USD", lp_shares=100, reason="bad"),
    )

    assert result.ok is False
    assert result.reason == "LP policy is disabled"


def test_lp_validation_rejects_missing_allowance(tmp_path):
    validator = validator_with_values(tmp_path, tech_allowance=99)

    result = validator.validate_lp_decision(
        "0xlp",
        LPDecision(
            action="ADD_LIQUIDITY",
            pool_id="TECH-USD",
            amount_a=100,
            amount_b=100,
            reason="bad",
        ),
    )

    assert result.ok is False
    assert result.reason == "insufficient base token allowance"


def test_lp_validation_rejects_policy_limits(tmp_path):
    validator = validator_with_values(tmp_path, lp_policy=(True, 99, 50, 20, 10, 123, 3600))

    add = validator.validate_lp_decision(
        "0xlp",
        LPDecision(action="ADD_LIQUIDITY", pool_id="TECH-USD", amount_a=100, amount_b=100, reason="bad"),
    )
    remove = validator.validate_lp_decision(
        "0xlp",
        LPDecision(action="REMOVE_LIQUIDITY", pool_id="TECH-USD", lp_shares=51, reason="bad"),
    )
    collect = validator.validate_lp_decision(
        "0xlp",
        LPDecision(action="COLLECT_FEES", pool_id="TECH-USD", lp_shares=1, reason="bad"),
    )

    assert add.reason == "liquidity add exceeds policy limit"
    assert remove.reason == "liquidity remove exceeds policy limit"
    assert collect.reason == "fee withdrawal exceeds policy limit"
