import pytest

from agents import config


def set_required_env(monkeypatch):
    values = {
        "SEPOLIA_RPC_URL": "https://example.invalid",
        "TRADER_PRIVATE_KEYS": "0xtrader1,0xtrader2",
        "TRADER_MODELS": "model-a,model-b",
        "LP_PRIVATE_KEYS": "0xlp1",
        "LP_MODELS": "model-lp",
        "TOKEN_A_ADDRESS": "0xa",
        "TOKEN_B_ADDRESS": "0xb",
        "LP_TOKEN_ADDRESS": "0xlp",
        "POLICY_ADDRESS": "0xp",
        "POOL_ADDRESS": "0xpool",
        "VAULT_ADDRESS": "0xvault",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_load_reads_amm_contract_addresses_and_agent_pairs(monkeypatch):
    set_required_env(monkeypatch)

    loaded = config.load()

    assert loaded.token_a == "0xa"
    assert loaded.token_b == "0xb"
    assert loaded.lp_token == "0xlp"
    assert loaded.pool == "0xpool"
    assert [trader.model for trader in loaded.traders] == ["model-a", "model-b"]
    assert [lp.private_key for lp in loaded.lps] == ["0xlp1"]


def test_load_rejects_mismatched_lp_keys_and_models(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("LP_MODELS", "model-a,model-b")

    with pytest.raises(RuntimeError, match="LP_PRIVATE_KEYS has 1 entries"):
        config.load()
