from datetime import UTC, datetime

from api.models import AgentSnapshot, PoolSnapshot, Session, SessionSummary, TimelineEvent
from api.main import create_app
from api.sample_data import build_sample_session
from api.session_store import SessionStore


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
