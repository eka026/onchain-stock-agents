import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware

from api.models import Session, SessionListItem
from api.sample_data import build_sample_session
from api.session_store import SessionStore


def create_app(store: SessionStore | None = None) -> FastAPI:
    app = FastAPI(title="On-chain Stock Agents Dashboard API")
    session_store = store or SessionStore()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/sessions", response_model=list[SessionListItem])
    def list_sessions() -> list[SessionListItem]:
        return session_store.list_sessions()

    @app.get("/api/sessions/{session_id}", response_model=Session)
    def get_session(session_id: str) -> Session:
        session = session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    @app.post("/api/sessions/import-demo", response_model=Session, status_code=201)
    def import_demo_session() -> Session:
        return session_store.save_session(build_sample_session())

    @app.post("/api/sessions/import-live", response_model=Session, status_code=201)
    def import_live_session() -> Session:
        scenario_path = os.environ.get("SCENARIO_PATH", "data/scenarios/demo.json")
        rpc_url = os.environ.get("RPC_URL") or os.environ.get("SEPOLIA_RPC_URL")
        if not rpc_url:
            raise HTTPException(status_code=503, detail="RPC_URL env var not set")
        network = "sepolia" if "sepolia" in rpc_url.lower() else "local"
        try:
            from agents.session_export import build_session_from_chain

            live_session = build_session_from_chain(
                scenario_path=scenario_path,
                rpc_url=rpc_url,
                network=network,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Chain read failed: {exc}") from exc
        return session_store.save_session(live_session)

    return app


app = create_app()
