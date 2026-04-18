#!/usr/bin/env bash
# Quick setup script — run once after cloning

set -e

echo "==> Creating virtual environment..."
uv venv .venv

echo "==> Installing dependencies..."
uv pip install -r requirements.txt

echo "==> Copying .env.example to .env..."
[ -f .env ] || cp .env.example .env

echo ""
echo "Done! Next steps:"
echo "  1. Edit .env and add your ANTHROPIC_API_KEY"
echo "  2. Put Jenkins log files in data/logs/"
echo "  3. Run: uvicorn main:app --reload"
echo "  4. Open http://localhost:8000 and click 'Ingest Logs'"
