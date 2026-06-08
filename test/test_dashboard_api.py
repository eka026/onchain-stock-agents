from datetime import UTC, datetime

from api.models import AgentSnapshot, PoolSnapshot, Session, SessionSummary, TimelineEvent
from api.main import create_app
from api.sample_data import build_sample_session
from api.session_store import SessionStore
from test.test_chain_contracts import scenario


def test_session_models_serialize_large_amounts_as_strings() -> None:
    created_at = datetime(2026, 5, 26, 10, 0, tzinfo=UTC)
    session = Session(
        id="sample-session",
        name="Sample Agent Run",
        source="sample",
        scenario_path="data/scenarios/demo.json",
        network="sample",
        created_at=created_at,
        updated_at=created_at,
        summary=SessionSummary(
            agent_count=1,
            event_count=1,
            confirmed_tx_count=1,
            rejected_count=0,
        ),
        agents=[
            AgentSnapshot(
                id="trader:0xabc",
                type="trader",
                label="Trader 0",
                address="0xabc",
                balances={"USD": "1000000000000000000"},
            )
        ],
        pools=[
            PoolSnapshot(
                id="TECH-USD",
                base_symbol="TECH",
                quote_symbol="USD",
                spot_price="1000000000000000000",
                reserve_a="500000000000000000000",
                reserve_b="500000000000000000000",
                fee_bps=30,
            )
        ],
        events=[
            TimelineEvent(
                id="event-1",
                kind="transaction",
                agent_id="trader:0xabc",
                agent_type="trader",
                pool_id="TECH-USD",
                action="SWAP",
                status="confirmed",
                summary="Trader swapped USD for TECH.",
                tx_hash="0x123",
                portfolio_delta={"USD": "-1000000000000000000", "TECH": "990000000000000000"},
            )
        ],
    )

    payload = session.model_dump(mode="json", by_alias=True)

    assert payload["scenarioPath"] == "data/scenarios/demo.json"
    assert payload["summary"]["confirmedTxCount"] == 1
    assert payload["agents"][0]["balances"]["USD"] == "1000000000000000000"
    assert payload["pools"][0]["spotPrice"] == "1000000000000000000"
    assert payload["events"][0]["portfolioDelta"]["USD"] == "-1000000000000000000"


def test_sample_session_contains_compact_dashboard_timeline() -> None:
    session = build_sample_session()

    assert session.id == "sample-session"
    assert session.source == "sample"
    assert session.summary.agent_count == 3
    assert session.summary.confirmed_tx_count == 2
    assert session.summary.rejected_count == 1
    assert len(session.agents) == 3
    assert len(session.pools) == 2
    assert [event.kind for event in session.events] == [
        "news",
        "agent_decision",
        "validation",
        "transaction",
        "portfolio_update",
        "agent_decision",
        "validation",
    ]
    assert session.agents[0].balances["USD"] == "995000000000000000000"
    assert session.events[4].portfolio_delta == {
        "USD": "-5000000000000000000",
        "TECH": "4935790171985306494",
    }


def test_live_chain_import_reconstructs_agents_and_transaction_events(monkeypatch) -> None:
    from agents import chain
    from agents import session_export
    from agents.news_feed import NewsFeed

    class FakeEvent:
        def __init__(self, logs):
            self.logs = logs

        def get_logs(self, fromBlock=0):
            return [log for log in self.logs if log["blockNumber"] >= fromBlock]

    class FakeEvents:
        Swap = FakeEvent([
            {
                "blockNumber": 12,
                "transactionHash": b"\x12\x34",
                "args": {
                    "trader": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
                    "tokenIn": "0xusd",
                    "amountIn": 100,
                    "amountOut": 45,
                },
            }
        ])
        LiquidityAdded = FakeEvent([
            {
                "blockNumber": 10,
                "transactionHash": b"\xab\xcd",
                "args": {
                    "provider": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
                    "amountA": 1_000,
                    "amountB": 1_000,
                    "lpShares": 1_000,
                },
            }
        ])
        LiquidityRemoved = FakeEvent([])

    class FakeVaultEvents:
        FeesCollected = FakeEvent([])

    class FakePoolContract:
        events = FakeEvents()

    class FakeVaultContract:
        events = FakeVaultEvents()

    class FakeRegistry:
        scenario = scenario()

        def __init__(self):
            empty_events = type(
                "EmptyEvents",
                (),
                {
                    "Swap": FakeEvent([]),
                    "LiquidityAdded": FakeEvent([]),
                    "LiquidityRemoved": FakeEvent([]),
                },
            )()
            self.pools = {}
            for pool in self.scenario.pools:
                pool_contract = FakePoolContract() if pool.id == "TECH-USD" else type("EmptyPool", (), {"events": empty_events})()
                self.pools[pool.id] = type(
                    "PoolContracts",
                    (),
                    {"pool": pool_contract, "vault": FakeVaultContract()},
                )()

        def pool_contracts(self, pool_id):
            return self.pools[pool_id]

    class FakeReader:
        def __init__(self, registry):
            self.registry = registry

        def reserves(self, pool_id):
            return (1_000, 2_000)

        def spot_price(self, pool_id):
            return 2 * 10**18

        def pool_fee_bps(self, pool_id):
            return 30

        def spot_price_history(self, pool_id):
            return [10**18, 2 * 10**18]

        def token_balance(self, symbol, account):
            return 100 if symbol == "USD" else 0

        def lp_balance(self, pool_id, account):
            return 50

    monkeypatch.setattr(NewsFeed, "load_scenario", lambda path: scenario())
    monkeypatch.setattr(chain.ContractRegistry, "from_rpc", lambda loaded_scenario, rpc_url: FakeRegistry())
    monkeypatch.setattr(chain, "ChainReader", FakeReader)
    monkeypatch.setenv(
        "TRADER_PRIVATE_KEYS",
        "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    )
    monkeypatch.setenv(
        "LP_PRIVATE_KEYS",
        "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    )
    monkeypatch.setenv("LIVE_IMPORT_EVENT_SOURCE", "chain")

    session = session_export.build_session_from_chain(
        scenario_path="data/scenarios/sepolia.json",
        rpc_url="https://sepolia.example",
        network="sepolia",
    )

    assert session.summary.agent_count == 2
    assert session.summary.event_count == 2
    assert session.summary.confirmed_tx_count == 2
    assert [event.action for event in session.events] == ["ADD_LIQUIDITY", "SWAP"]
    assert session.events[1].agent_id == "trader:0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
    assert session.events[1].tx_hash == "0x1234"
    assert session.agents[0].balances["USD"] == "100"
    assert session.agents[1].balances["TECH-USD-LP"] == "50"


def test_live_import_uses_local_event_log_by_default(monkeypatch, tmp_path) -> None:
    from agents import chain
    from agents import session_export
    from agents.news_feed import NewsFeed

    log_path = tmp_path / "events.json"
    log_path.write_text(
        "\n".join([
            '{"timestamp":"2026-06-06T15:00:00+00:00","event":{"type":"decision","agent":"trader","address":"0xabc","action":"SWAP","pool_id":"TECH-USD","reason":"buy tech","token_in":"USD","amount_in":100}}',
            '{"timestamp":"2026-06-06T15:00:01+00:00","event":{"type":"action","action":"SWAP","trader":"0xabc","pool_id":"TECH-USD","token_in":"USD","amount_in":100,"tx_hash":"0xaaa"}}',
            '{"timestamp":"2026-06-06T15:00:02+00:00","event":{"type":"execution_result","action":"SWAP","trader":"0xabc","tx_hash":"0xaaa","status":"CONFIRMED","event_data":{"trader":"0xabc","tokenIn":"0xusd","amountIn":100,"amountOut":45},"reason":null}}',
        ])
        + "\n",
        encoding="utf-8",
    )

    class RaisingEvent:
        def get_logs(self, **_kwargs):
            raise AssertionError("chain log scan should not run in local import mode")

    class FakeContract:
        events = type(
            "Events",
            (),
            {
                "Swap": RaisingEvent(),
                "LiquidityAdded": RaisingEvent(),
                "LiquidityRemoved": RaisingEvent(),
                "FeesCollected": RaisingEvent(),
            },
        )()

    class FakeRegistry:
        scenario = scenario()

        def __init__(self):
            self.pools = {
                pool.id: type("PoolContracts", (), {"pool": FakeContract(), "vault": FakeContract()})()
                for pool in self.scenario.pools
            }

        def pool_contracts(self, pool_id):
            return self.pools[pool_id]

    class FakeReader:
        def __init__(self, registry):
            self.registry = registry

        def reserves(self, pool_id):
            return (1_000, 2_000)

        def spot_price(self, pool_id):
            return 2 * 10**18

        def pool_fee_bps(self, pool_id):
            return 30

        def token_balance(self, symbol, account):
            return 100 if symbol == "USD" else 0

        def lp_balance(self, pool_id, account):
            return 50

    monkeypatch.setattr(NewsFeed, "load_scenario", lambda path: scenario())
    monkeypatch.setattr(chain.ContractRegistry, "from_rpc", lambda loaded_scenario, rpc_url: FakeRegistry())
    monkeypatch.setattr(chain, "ChainReader", FakeReader)
    monkeypatch.setenv("LIVE_IMPORT_LOG_PATH", str(log_path))
    monkeypatch.delenv("LIVE_IMPORT_EVENT_SOURCE", raising=False)
    monkeypatch.setenv(
        "TRADER_PRIVATE_KEYS",
        "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    )
    monkeypatch.setenv("LP_PRIVATE_KEYS", "")

    session = session_export.build_session_from_chain(
        scenario_path="data/scenarios/sepolia.json",
        rpc_url="https://sepolia.example",
        network="sepolia",
    )

    assert session.summary.event_count == 2
    assert [event.kind for event in session.events] == ["agent_decision", "transaction"]
    assert session.events[1].tx_hash == "0xaaa"


def test_session_store_saves_and_loads_sessions(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = build_sample_session()

    store.save_session(session)

    assert store.get_session(session.id) == session
    assert [item.id for item in store.list_sessions()] == [session.id]


def test_session_store_returns_none_for_missing_session(tmp_path) -> None:
    store = SessionStore(tmp_path)

    assert store.get_session("missing") is None


def test_health_endpoint_returns_ok(tmp_path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_app(SessionStore(tmp_path)))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sessions_api_imports_and_returns_sample_session(tmp_path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_app(SessionStore(tmp_path)))

    assert client.get("/api/sessions").json() == []

    import_response = client.post("/api/sessions/import-demo")
    assert import_response.status_code == 201
    imported = import_response.json()
    assert imported["id"] == "sample-session"
    assert imported["summary"]["eventCount"] == 7

    list_response = client.get("/api/sessions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == ["sample-session"]

    detail_response = client.get("/api/sessions/sample-session")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["events"][0]["kind"] == "news"
    assert detail["agents"][0]["balances"]["USD"] == "995000000000000000000"


def test_sessions_api_returns_404_for_missing_session(tmp_path) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_app(SessionStore(tmp_path)))

    response = client.get("/api/sessions/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"
