@echo off
setlocal

:: ============================================================================
:: GeoAI Final Project - Automated Test Suite Runner
:: ============================================================================
:: Double-click this script to run the pytest test suite validating the RAG
:: backend contract, typing, and all spatial query scenarios.
:: ============================================================================

cd /d "%~dp0"

title GeoAI Project - Automated Test Suite

echo ============================================================================
echo                     GEOAI PROJECT - PYTEST VALIDATOR
echo ============================================================================
echo.

:: Activate local virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo Running tests via pytest...
echo.
python -m pytest test_app.py -v

echo.
echo ============================================================================
pause
