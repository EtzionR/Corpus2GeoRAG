#!/usr/bin/env bash
# ==============================================================================
# GeoAI Final Project - Automated Unix/macOS Launcher
# ==============================================================================
# Cross-platform runner script for Linux / macOS coworkers.
# Usage:
#   chmod +x run_app.sh
#   ./run_app.sh
# ==============================================================================

set -e

echo "============================================================================"
echo "                GEOAI FINAL PROJECT - RUNNER & BOOTSTRAPPER"
echo "============================================================================"
echo ""

# Check python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.10+."
    exit 1
fi

echo "[1/4] Python detected: $(python3 --version)"

# Setup venv
if [ ! -d ".venv" ]; then
    echo "[2/4] Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

# Activate venv
echo "[3/4] Activating virtual environment..."
source .venv/bin/activate

# Install requirements
echo "Checking and installing dependencies..."
python -m pip install -r requirements.txt --quiet

# Launch Streamlit
echo "============================================================================"
echo "[4/4] Launching GeoAI Streamlit Application..."
echo "============================================================================"
python -m streamlit run app.py
