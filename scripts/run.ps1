$ErrorActionPreference = 'Stop'

if (-not (Test-Path .\.venv)) {
  python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1

python -m pip install -U pip
pip install -r requirements.txt

# This repo uses a "src/" layout; install editable so `python -m gatewatch.main` works.
pip install -e .

# Optional: create .env from example if it doesn't exist
if (-not (Test-Path .\.env) -and (Test-Path .\configs\example.env)) {
  Copy-Item .\configs\example.env .\.env
}

python -m gatewatch.main
