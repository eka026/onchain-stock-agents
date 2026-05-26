import json
import os
from pathlib import Path

from api.models import Session, SessionListItem


class SessionStore:
    def __init__(self, root: str | Path = "data/dashboard_sessions"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list_sessions(self) -> list[SessionListItem]:
        sessions = [self._read_session(path) for path in self.root.glob("*.json")]
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return [
            SessionListItem(
                id=session.id,
                name=session.name,
                source=session.source,
                created_at=session.created_at,
                updated_at=session.updated_at,
                summary=session.summary,
            )
            for session in sessions
        ]

    def get_session(self, session_id: str) -> Session | None:
        path = self._path_for(session_id)
        if not path.exists():
            return None
        return self._read_session(path)

    def save_session(self, session: Session) -> Session:
        path = self._path_for(session.id)
        tmp_path = path.with_suffix(".tmp")
        payload = session.model_dump(mode="json", by_alias=True)
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, path)
        return session

    def _read_session(self, path: Path) -> Session:
        return Session.model_validate_json(path.read_text(encoding="utf-8"))

    def _path_for(self, session_id: str) -> Path:
        safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in session_id)
        return self.root / f"{safe_name}.json"
