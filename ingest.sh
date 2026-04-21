#!/usr/bin/env bash
# Run after the server is up (bash run.sh) to ingest Jenkins logs

source .venv/Scripts/activate
curl -X POST http://localhost:8000/api/jenkins/ingest
