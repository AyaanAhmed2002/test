@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Bruviti Invoice Extractor — Windows Quick Start
REM  Run this once after a fresh clone to set up and verify the project.
REM ─────────────────────────────────────────────────────────────────────────────

echo [1/4] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (echo ERROR: python not found. Install Python 3.11+. & exit /b 1)

echo [2/4] Installing dependencies...
.venv\Scripts\pip install --quiet -r requirements.txt
if errorlevel 1 (echo ERROR: pip install failed. & exit /b 1)

echo [3/4] Generating synthetic test invoices...
.venv\Scripts\python scripts\generate_test_invoices.py
if errorlevel 1 (echo ERROR: test data generation failed. & exit /b 1)

echo [4/4] Running test suite...
.venv\Scripts\python -m pytest tests\ -v --tb=short
if errorlevel 1 (echo WARNING: some tests failed — review output above.)

echo.
echo Setup complete.
echo To start the server:
echo   .venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
echo Then open: http://127.0.0.1:8000
