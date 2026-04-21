#!/usr/bin/env bash
# Start the server. In a second terminal, run: bash ingest.sh

source .venv/Scripts/activate
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
