# GateWatch (Python)
![LOGO](/Neis%20System.png = 250x250)
A beginner-friendly, real-world starter project for a gate/parking entrance camera system that:
- Detects **vehicles arriving** (so reception gets notified and drivers don’t need to honk)
- Detects **people / unknown objects** near the gate (security alert)
- Reads **license plates** and matches them against a **whitelist**
  - owner -> notify reception (“Owner arrived”)
  - boss -> notify reception (“Boss arrived”)
  - unknown -> notify reception (“Visitor arrived”)

## Real-world flow (what the system does)
1. **Camera feed**: an IP camera / USB camera provides frames.
2. **Motion / arrival detection**: detect that “something is approaching the gate” (vehicle/person).
3. **Object detection**:
   - vehicle class -> triggers “vehicle arrival” event
   - person class -> triggers “person at gate” event
4. **Plate detection + OCR** (only when vehicle detected): crop plate region and read text.
5. **Decision**:
   - plate matches whitelist -> classify as `owner` / `boss`
   - plate not in whitelist -> classify as `visitor`
6. **Alert routing**:
   - send a message to reception (console now, webhook later)
   - (optional) store events to a DB / file for audit

## What’s in this repo
- `src/gatewatch/main.py`: FastAPI app + entrypoint.
- `src/gatewatch/pipeline.py`: the “camera -> detections -> events” pipeline (stubs).
- `src/gatewatch/notify.py`: notification sending (console/webhook stub).
- `configs/`: example configs (whitelist, env).
- `scripts/`: local run helpers for Windows PowerShell.

## Step-by-step setup (Windows / PowerShell)
### Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt

# IMPORTANT for this repo: code lives under src/ ("src layout"), so install the package for imports to work
pip install -e .
```

### Run the API
```powershell
# Dev server (uses uvicorn.run(..., reload=True) in src/gatewatch/main.py)
python -m gatewatch.main

# Health check
# http://127.0.0.1:8000/health

# Simulate an event (persists to SQLite + notifies)
# POST http://127.0.0.1:8000/simulate?subject=vehicle&plate_text=ABC123

# List events from SQLite
# GET http://127.0.0.1:8000/events?limit=100
```

Helper script:
```powershell
# Note: scripts/run.ps1 currently installs requirements and runs the module.
# If you hit ModuleNotFoundError: gatewatch, run `pip install -e .` once in the venv.
.\scripts\run.ps1
```

### Tests
There’s a minimal smoke test in `tests/test_imports.py`.

This repo does not currently pin a test runner dependency; install `pytest` in your venv before running tests.

```powershell
pip install pytest

# Run all tests
python -m pytest

# Run a single test file
python -m pytest .\tests\test_imports.py

# Run a single test (substring match)
python -m pytest .\tests\test_imports.py -k test_imports
```

### Lint / typecheck
No linter/type-checker is currently configured in the repo (no ruff/flake8/mypy/pyright config found).

## Architecture overview

### Big picture
This repo is a starter scaffold for a “gate/parking entrance camera” system:
- A FastAPI service exposes endpoints to simulate detections.
- A vision pipeline class is responsible for turning camera frames into structured `DetectionEvent`s (currently stubbed).
- A notifier sends those events to a console log and optionally to a webhook.

### Key modules
- `src/gatewatch/main.py`
  - `create_app()` loads `.env` via `python-dotenv`, loads a whitelist JSON, constructs `GateWatchPipeline` + `Notifier`, and wires HTTP endpoints.
  - Endpoints:
    - `GET /health`: basic health check
    - `POST /simulate`: creates a `DetectionEvent` (optionally classifying plates) and sends it via notifier
  - `__main__` starts Uvicorn with reload.

- `src/gatewatch/pipeline.py`
  - Domain model:
    - `SubjectType` (vehicle/person/object)
    - `ArrivalType` (owner/boss/visitor/unknown)
    - `DetectionEvent` dataclass: the event payload shared between pipeline + notifier
  - `GateWatchPipeline`
    - `classify_plate()` maps plate text to an `ArrivalType` using the loaded whitelist
    - `process_one_tick()` is currently a stub (intended to become the camera/detection loop)

- `src/gatewatch/notify.py`
  - `Notifier.send()` always logs the event and optionally POSTs JSON to a webhook.
  - `notifier_from_env()` reads `GATEWATCH_WEBHOOK_URL`.

### Configuration
- `.env` (optional) is loaded at startup; see `configs/example.env`.
- `GATEWATCH_WHITELIST_PATH`
  - Default: `configs/whitelist.json`
  - Format: JSON object mapping `PLATE_TEXT` -> role string (`owner` / `boss`).
- `GATEWATCH_WEBHOOK_URL` (optional)
  - If set, `Notifier` will POST events to this URL.