@echo off
rem GeoRAG: double-click to run the agent and the map on this computer.
rem The first run sets up Python packages (a few minutes) and asks once for the OpenRouter key,
rem which is saved in AgentRag\.env (git ignores it: it is never uploaded). The rest is in AgentRag\launch.py.
cd /d "%~dp0"
title GeoRAG
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH", then double-click RUN_GEORAG.bat again.
    pause
    exit /b 1
)
%PY% AgentRag\launch.py
if errorlevel 1 pause
