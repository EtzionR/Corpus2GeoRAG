@echo off
setlocal
REM ==============================================================================
REM GeoAI Final Project - Automated Unit, Performance & Quality Gate Runner
REM ==============================================================================
echo.
echo ==============================================================================
echo   GeoAI Tactical Intelligence - Unit, Performance ^& Quality Gate Suite
echo ==============================================================================
echo.

cd /d "%~dp0"

set "PYTHON_EXE="
if exist "..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=..\.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PYTHON_EXE=python"
    ) else (
        echo [ERROR] Python executable not found. Please install Python or create a .venv virtual environment.
        exit /b 1
    )
)

echo [STEP 1/2] Running Static AST Invariant ^& File-to-Test Pairing Audit...
"%PYTHON_EXE%" verify_quality_gate.py --check-only
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [BLOCKED] Static Quality Gate or File-to-Test Pairing Audit FAILED!
    if /I not "%~1"=="--ci" if /I not "%~1"=="--non-interactive" pause
    exit /b %ERRORLEVEL%
)

echo.
echo [STEP 2/2] Running Full Unit Test ^& Performance Benchmark Suite...
"%PYTHON_EXE%" -m pytest test_app.py -v
set "TEST_EXIT_CODE=%ERRORLEVEL%"

echo.
if %TEST_EXIT_CODE% EQU 0 (
    echo [SUCCESS] All 140 unit tests, state-loop checks, and latency ceilings passed!
) else (
    echo [FAILED] Unit test failure or latency ceiling regression detected - Exit Code: %TEST_EXIT_CODE%
)
echo.

if /I not "%~1"=="--ci" if /I not "%~1"=="--non-interactive" pause
exit /b %TEST_EXIT_CODE%
