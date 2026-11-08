#!/usr/bin/env bash
# ==============================================================================
# GeoAI Final Project - Automated Unit, Performance & Quality Gate Runner (POSIX)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================================================="
echo "  GeoAI Tactical Intelligence - Unit, Performance & Quality Gate Suite"
echo "=============================================================================="

if [ -x "../.venv/Scripts/python.exe" ]; then
    PYTHON_EXE="../.venv/Scripts/python.exe"
elif [ -x ".venv/Scripts/python.exe" ]; then
    PYTHON_EXE=".venv/Scripts/python.exe"
elif [ -x "../.venv/bin/python" ]; then
    PYTHON_EXE="../.venv/bin/python"
elif [ -x ".venv/bin/python" ]; then
    PYTHON_EXE=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXE="python"
else
    echo "[ERROR] Python executable not found."
    exit 1
fi

echo "[STEP 1/2] Running Static AST Invariant & File-to-Test Pairing Audit..."
"$PYTHON_EXE" verify_quality_gate.py --check-only

echo "[STEP 2/2] Running Full Unit Test & Performance Benchmark Suite (pytest)..."
"$PYTHON_EXE" -m pytest test_app.py -v

echo "[SUCCESS] All unit tests, state-loop checks, and latency ceilings passed!"
