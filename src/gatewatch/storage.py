from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from .pipeline import ArrivalType, DetectionEvent, SubjectType


class EventStore:
    """Very small SQLite event store.

    Implementation notes:
    - Opens a new SQLite connection per operation for simpler thread-safety.
    - Stores a full JSON payload for forward compatibility.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_env(cls) -> "EventStore":
        db_path = Path(os.getenv("GATEWATCH_DB_PATH", "data/gatewatch.db"))
        return cls(db_path=db_path)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts_utc TEXT NOT NULL,
                  camera_id TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  arrival TEXT NOT NULL,
                  plate_text TEXT NULL,
                  confidence REAL NULL,
                  payload_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def insert(self, event: DetectionEvent) -> int:
        payload = _event_to_payload(event)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (ts_utc, camera_id, subject, arrival, plate_text, confidence, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.ts_utc.isoformat(),
                    event.camera_id,
                    event.subject.value,
                    event.arrival.value,
                    event.plate_text,
                    event.confidence,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get(self, event_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, payload_json FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()

        if row is None:
            return None

        _id, payload_json = row
        try:
            payload = json.loads(payload_json)
        except Exception:
            logger.exception("Failed to parse stored payload_json for event {}", _id)
            return {"id": _id, "payload": payload_json}

        return {"id": _id, "payload": payload}

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, payload_json
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        out: list[dict[str, Any]] = []
        for _id, payload_json in rows:
            try:
                out.append({"id": int(_id), "payload": json.loads(payload_json)})
            except Exception:
                out.append({"id": int(_id), "payload": payload_json})
        return out


def _event_to_payload(event: DetectionEvent) -> dict[str, Any]:
    # asdict handles dataclass fields; we then normalize enums + datetime.
    raw = asdict(event)
    raw["ts_utc"] = event.ts_utc.isoformat()
    raw["subject"] = event.subject.value if isinstance(event.subject, SubjectType) else str(event.subject)
    raw["arrival"] = event.arrival.value if isinstance(event.arrival, ArrivalType) else str(event.arrival)
    return raw
