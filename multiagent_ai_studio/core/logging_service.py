from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .database import Database
from .models import LogEvent


class LogService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.subscribers = []

    def subscribe(self, callback) -> None:
        self.subscribers.append(callback)

    def log(self, event_type: str, message: str, *, agent_id: int | None = None, project_id: int | None = None, level: str = "INFO") -> LogEvent:
        event = self.db.add_log(LogEvent(None, event_type, message, agent_id, project_id, level, datetime.utcnow().isoformat()))
        for callback in list(self.subscribers):
            callback(event)
        return event

    def export(self, path: Path) -> None:
        rows = self.db.list_logs(limit=100000)
        path.write_text("\n".join(f"[{r.created_at}] {r.level} {r.event_type}: {r.message}" for r in rows), encoding="utf-8")
