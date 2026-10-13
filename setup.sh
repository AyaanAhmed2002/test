#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Bruviti Invoice Extractor — Linux / macOS Quick Start
#  Run this once after a fresh clone to set up and verify the project.
# ─────────────────────────────────────────────────────────────────────────────
set -e

echo "[1/4] Creating virtual environment..."
python3 -m venv .venv

echo "[2/4] Installing dependencies..."
.venv/bin/pip install --quiet -r requirements.txt

echo "[3/4] Generating synthetic test invoices..."
.venv/bin/python scripts/generate_test_invoices.py

echo "[4/4] Running test suite..."
.venv/bin/python -m pytest tests/ -v --tb=short

echo ""
echo "Setup complete."
echo "To start the server:"
echo "  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
echo "Then open: http://127.0.0.1:8000"
