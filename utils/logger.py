import json
from datetime import datetime, timezone
from pathlib import Path

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "events.json"


def log(event: dict) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event}
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
