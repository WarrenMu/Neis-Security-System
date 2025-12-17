from __future__ import annotations

from pathlib import Path

from gatewatch.pipeline import ArrivalType, DetectionEvent, SubjectType, now_utc
from gatewatch.storage import EventStore


def test_event_store_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "gatewatch.db"
    store = EventStore(db_path=db_path)

    event = DetectionEvent(
        ts_utc=now_utc(),
        subject=SubjectType.VEHICLE,
        arrival=ArrivalType.VISITOR,
        plate_text="ABC123",
        confidence=0.9,
        camera_id="test-cam",
    )

    event_id = store.insert(event)
    assert event_id > 0

    got = store.get(event_id)
    assert got is not None
    assert got["id"] == event_id
    assert isinstance(got["payload"], dict)
    assert got["payload"]["camera_id"] == "test-cam"

    recent = store.list_recent(limit=10)
    assert recent
    assert recent[0]["id"] == event_id
