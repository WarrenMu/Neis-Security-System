from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from loguru import logger

from .notify import notifier_from_env
from .pipeline import ArrivalType, DetectionEvent, GateWatchPipeline, SubjectType, now_utc
from .storage import EventStore


def load_whitelist(path: Path) -> dict[str, str]:
    if not path.exists():
        logger.warning("Whitelist file not found: {} (using empty whitelist)", path)
        return {}

    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("whitelist.json must be an object mapping plate -> role")
    # normalize to str->str
    return {str(k): str(v) for k, v in data.items()}


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> FastAPI:
    load_dotenv()

    whitelist_path = Path(os.getenv("GATEWATCH_WHITELIST_PATH", "configs/whitelist.json"))
    pipeline = GateWatchPipeline.from_env(whitelist=load_whitelist(whitelist_path))
    notifier = notifier_from_env()
    store = EventStore.from_env()

    stop = threading.Event()

    def live_loop() -> None:
        interval_ms = int(os.getenv("GATEWATCH_TICK_INTERVAL_MS", "100"))
        sleep_s = max(0.01, interval_ms / 1000.0)

        while not stop.is_set():
            try:
                event = pipeline.process_one_tick()
                if event is not None:
                    event_id = store.insert(event)
                    notifier.send(event)
                    logger.debug("Stored event id={}", event_id)
            except Exception:
                logger.exception("Live pipeline loop error")

            time.sleep(sleep_s)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        thread: threading.Thread | None = None

        if _truthy_env("GATEWATCH_ENABLE_LIVE_PIPELINE", "0"):
            thread = threading.Thread(target=live_loop, name="gatewatch-live", daemon=True)
            thread.start()
            logger.info("Live pipeline enabled")

        try:
            yield
        finally:
            stop.set()
            try:
                pipeline.close()
            except Exception:
                logger.exception("Failed to close pipeline")

            if thread is not None:
                thread.join(timeout=2)

    app = FastAPI(title="GateWatch", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/simulate")
    def simulate(subject: SubjectType = SubjectType.VEHICLE, plate_text: str = "ABC123") -> dict[str, object]:
        arrival = ArrivalType.UNKNOWN
        if subject == SubjectType.VEHICLE and plate_text:
            arrival = pipeline.classify_plate(plate_text)

        event = DetectionEvent(
            ts_utc=now_utc(),
            subject=subject,
            arrival=arrival,
            plate_text=plate_text if subject == SubjectType.VEHICLE else None,
            confidence=0.99,
        )
        event_id = store.insert(event)
        notifier.send(event)
        return {"result": "sent", "id": event_id}

    @app.get("/events")
    def list_events(limit: int = 100) -> list[dict[str, object]]:
        return store.list_recent(limit=limit)

    @app.get("/events/{event_id}")
    def get_event(event_id: int) -> dict[str, object]:
        got = store.get(event_id)
        if got is None:
            raise HTTPException(status_code=404, detail="event not found")
        return got

    return app


app = create_app()


def _dev_loop() -> None:
    """Optional: run a tiny loop without FastAPI.

    Prefer enabling GATEWATCH_ENABLE_LIVE_PIPELINE=1 and running the API instead.
    """

    load_dotenv()
    whitelist_path = Path(os.getenv("GATEWATCH_WHITELIST_PATH", "configs/whitelist.json"))
    pipeline = GateWatchPipeline.from_env(whitelist=load_whitelist(whitelist_path))
    notifier = notifier_from_env()
    store = EventStore.from_env()

    while True:
        event = pipeline.process_one_tick()
        if event is not None:
            store.insert(event)
            notifier.send(event)
        time.sleep(0.1)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gatewatch.main:app", host="127.0.0.1", port=8000, reload=True)
