#!/usr/bin/env bash
# Quick setup script — run once after cloning

set -e

echo "==> Creating virtual environment..."
python -m venv .venv

echo "==> Installing dependencies..."
source .venv/Scripts/activate
pip install -r requirements.txt

echo ""
echo "Done! Start the server with:"
echo "  bash run.sh"
echo "Then ingest logs with:"
echo "  bash ingest.sh"
