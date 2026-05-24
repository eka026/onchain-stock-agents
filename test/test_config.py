import pytest
import json

from agents import config


def write_scenario(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text(
        json.dumps(
            {
                "seed": 438,
                "news_file": "data/news.json",
                "policy_address": "0xpolicy",
                "min_interval_ticks": 1,
                "max_interval_ticks": 2,
                "max_events": 1,
                "broadcast_to_all_traders": True,
                "tokens": [
                    {"symbol": "USD", "address": "0xusd"},
                    {"symbol": "AAPL", "address": "0xaapl"},
                    {"symbol": "NVDA", "address": "0xnvda"},
                ],
                "pools": [
                    {
                        "id": "AAPL-USD",
                        "base_symbol": "AAPL",
                        "quote_symbol": "USD",
                        "pool_address": "0xaaplpool",
                        "lp_token_address": "0xaapllp",
                        "vault_address": "0xaaplvault",
                    },
                    {
                        "id": "NVDA-USD",
                        "base_symbol": "NVDA",
                        "quote_symbol": "USD",
                        "pool_address": "0$nvdapool",
                        "lp_token_address": "0$nvdalp",
                        "vault_address": "0$nvdavault",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def set_required_env(monkeypatch, tmp_path):
    scenario_path = write_scenario(tmp_path)
    values = {
        "SEPOLIA_RPC_URL": "https://example.invalid",
        "TRADER_PRIVATE_KEYS": "0xtrader1,0xtrader2",
        "TRADER_MODELS": "model-a,model-b",
        "LP_PRIVATE_KEYS": "0xlp1",
        "LP_MODELS": "model-lp",
        "SCENARIO_PATH": str(scenario_path),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_load_reads_scenario_and_agent_pairs(monkeypatch, tmp_path):
    set_required_env(monkeypatch, tmp_path)

    loaded = config.load()

    assert loaded.scenario_path.endswith("scenario.json")
    assert loaded.scenario.policy_address == "0xpolicy"
    assert [token.symbol for token in loaded.scenario.tokens] == ["USD", "AAPL", "NVDA"]
    assert [pool.id for pool in loaded.scenario.pools] == ["AAPL-USD", "NVDA-USD"]
    assert loaded.scenario.pools[0].lp_token_address == "0xaapllp"
    assert loaded.scenario.pools[0].vault_address == "0xaaplvault"
    assert [trader.model for trader in loaded.traders] == ["model-a", "model-b"]
    assert [lp.private_key for lp in loaded.lps] == ["0xlp1"]


def test_load_rejects_mismatched_lp_keys_and_models(monkeypatch, tmp_path):
    set_required_env(monkeypatch, tmp_path)
    monkeypatch.setenv("LP_MODELS", "model-a,model-b")

    with pytest.raises(RuntimeError, match="LP_PRIVATE_KEYS has 1 entries"):
        config.load()


def test_load_can_skip_unneeded_agent_pairs(monkeypatch, tmp_path):
    set_required_env(monkeypatch, tmp_path)
    monkeypatch.delenv("TRADER_PRIVATE_KEYS")
    monkeypatch.delenv("TRADER_MODELS")

    loaded = config.load(require_traders=False)

    assert loaded.traders == []
    assert [lp.private_key for lp in loaded.lps] == ["0xlp1"]
