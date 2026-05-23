import pytest

from agents.llm import LLMClient, LLMDecisionError, MockLLMClient, parse_lp_decision, parse_trader_decision
from agents.news_feed import PoolInfo


def pools():
    return [
        PoolInfo(
            id="TECH-USD",
            base_symbol="TECH",
            quote_symbol="USD",
            pool_address="0xtechpool",
            lp_token_address="0xtechlp",
            vault_address="0xtechvault",
        ),
        PoolInfo(
            id="FIN-USD",
            base_symbol="FIN",
            quote_symbol="USD",
            pool_address="0xfinpool",
            lp_token_address="0xfinlp",
            vault_address="0xfinvault",
        ),
    ]


def test_mock_trader_response_is_deterministic_for_same_observation():
    observation = {
        "news": {
            "headline": "Cloud software spending improves",
            "body": "Companies restarted server and database projects.",
        },
        "pools": pools(),
        "default_amount_in": 123,
    }

    first = MockLLMClient().decide_trader(observation)
    second = MockLLMClient().decide_trader(observation)

    assert first == second
    assert first.action == "SWAP"
    assert first.pool_id == "TECH-USD"
    assert first.token_in == "USD"
    assert first.amount_in == 123
    assert first.max_slippage_bps == 100
    assert first.deadline_seconds == 300


def test_mock_trader_holds_when_news_does_not_match_pool():
    decision = MockLLMClient().decide_trader(
        {
            "news": {
                "headline": "Unrelated municipal festival announced",
                "body": "Organizers expect larger attendance downtown.",
            },
            "pools": pools(),
        }
    )

    assert decision.action == "HOLD"
    assert decision.pool_id is None


def test_symbol_matching_uses_tokens_not_substrings():
    decision = MockLLMClient().decide_trader(
        {
            "news": {
                "headline": "Biotech company reports medical trial progress",
                "body": "Hospital buyers reviewed patient data after the announcement.",
            },
            "pools": pools(),
        }
    )

    assert decision.action == "HOLD"


def test_warehouse_keyword_routes_to_reit_when_reit_pool_exists():
    decision = MockLLMClient().decide_trader(
        {
            "news": {
                "headline": "Warehouse leasing shows stronger demand",
                "body": "Property owners reported higher occupancy after lease renewals.",
            },
            "pools": [
                *pools(),
                PoolInfo(
                    id="INDS-USD",
                    base_symbol="INDS",
                    quote_symbol="USD",
                    pool_address="0xindspool",
                    lp_token_address="0xindslp",
                    vault_address="0xindsvault",
                ),
                PoolInfo(
                    id="REIT-USD",
                    base_symbol="REIT",
                    quote_symbol="USD",
                    pool_address="0xreitpool",
                    lp_token_address="0xreitlp",
                    vault_address="0xreitvault",
                ),
            ],
        }
    )

    assert decision.action == "SWAP"
    assert decision.pool_id == "REIT-USD"


def test_mock_trader_supports_scripted_decision_response():
    client = MockLLMClient(
        trader_responses=[
            {
                "action": "SWAP",
                "pool_id": "FIN-USD",
                "token_in": "USD",
                "amount_in": 50,
                "reason": "Payment volumes improved.",
            }
        ]
    )

    decision = client.decide_trader({"pools": pools()})

    assert decision.action == "SWAP"
    assert decision.pool_id == "FIN-USD"
    assert decision.amount_in == 50


def test_mock_client_can_reset_scripted_response_indexes():
    client = MockLLMClient(
        trader_responses=[
            {
                "action": "SWAP",
                "pool_id": "TECH-USD",
                "token_in": "USD",
                "amount_in": 1,
                "reason": "first",
            }
        ]
    )

    assert client.decide_trader({"pools": pools()}).amount_in == 1
    assert client.decide_trader({"pools": pools()}).action == "HOLD"

    client.reset()

    assert client.decide_trader({"pools": pools()}).amount_in == 1


def test_mock_client_satisfies_llm_client_protocol():
    client: LLMClient = MockLLMClient()

    assert client.decide_trader({"pools": pools()}).action == "HOLD"


def test_llm_response_includes_provider_metadata_fields():
    response = MockLLMClient().trader_response({"pools": pools()})

    assert response.model == "mock"
    assert response.finish_reason is None
    assert response.usage is None
    assert response.latency_ms is None


def test_mock_lp_default_response_adds_liquidity_to_first_pool():
    decision = MockLLMClient().decide_lp(
        {
            "pools": pools(),
            "default_amount_a": 10,
            "default_amount_b": 20,
            "default_min_lp_shares": 5,
        }
    )

    assert decision.action == "ADD_LIQUIDITY"
    assert decision.pool_id == "TECH-USD"
    assert decision.amount_a == 10
    assert decision.amount_b == 20
    assert decision.min_lp_shares == 5


@pytest.mark.parametrize(
    ("mock_lp_action", "expected_action"),
    [
        ("REMOVE_LIQUIDITY", "REMOVE_LIQUIDITY"),
        ("COLLECT_FEES", "COLLECT_FEES"),
        ("HOLD", "HOLD"),
    ],
)
def test_mock_lp_supports_deterministic_action_variants(mock_lp_action, expected_action):
    decision = MockLLMClient().decide_lp(
        {
            "pools": pools(),
            "mock_lp_action": mock_lp_action,
            "default_lp_shares": 7,
        }
    )

    assert decision.action == expected_action
    if expected_action != "HOLD":
        assert decision.pool_id == "TECH-USD"
        assert decision.lp_shares == 7


def test_mock_lp_supports_scripted_decision_response():
    client = MockLLMClient(
        lp_responses=[
            {
                "action": "COLLECT_FEES",
                "pool_id": "FIN-USD",
                "lp_shares": 9,
                "reason": "Collecting fees.",
            }
        ]
    )

    decision = client.decide_lp({"pools": pools()})

    assert decision.action == "COLLECT_FEES"
    assert decision.pool_id == "FIN-USD"
    assert decision.lp_shares == 9


def test_invalid_json_responses_raise_without_provider_calls():
    client = MockLLMClient(invalid_json=True)

    with pytest.raises(LLMDecisionError, match="not valid JSON"):
        client.decide_trader({"pools": pools()})

    with pytest.raises(LLMDecisionError, match="not valid JSON"):
        client.decide_lp({"pools": pools()})


def test_parse_rejects_non_object_json():
    with pytest.raises(LLMDecisionError, match="JSON object"):
        parse_trader_decision("[]")


def test_parse_validates_decision_schema_and_pool_metadata():
    with pytest.raises(LLMDecisionError, match="unknown pool_id"):
        parse_trader_decision(
            '{"action":"SWAP","pool_id":"MISSING-USD","token_in":"USD","amount_in":1,"reason":"bad"}',
            pools=pools(),
        )

    with pytest.raises(LLMDecisionError, match="unknown pool_id"):
        parse_lp_decision(
            '{"action":"COLLECT_FEES","pool_id":"MISSING-USD","lp_shares":1,"reason":"bad"}',
            pools=pools(),
        )
