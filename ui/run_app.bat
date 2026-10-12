@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: GeoAI Final Project - Automated Windows Launcher
:: ============================================================================
:: This script provides a zero-friction, one-click launcher for the GeoAI
:: Streamlit application. When any team member clones this repository, double-
:: clicking this file will:
::   1. Verify Python availability.
::   2. Automatically create a local virtual environment (.venv) if not present.
::   3. Install or update all required packages from requirements.txt.
::   4. Launch the Streamlit application in the default web browser.
:: ============================================================================

cd /d "%~dp0"

title GeoAI Spatial Intelligence Hub - Launcher

echo ============================================================================
echo                GEOAI FINAL PROJECT - RUNNER ^& BOOTSTRAPPER
echo ============================================================================
echo.

:: 1. Check for Python installation
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python was not found in your system PATH.
    echo Please install Python 3.10 or higher from https://www.python.org/
    echo Make sure to check the box "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [1/4] Python detected:
python --version
echo.

:: 2. Create or verify virtual environment (.venv)
if not exist ".venv\Scripts\activate.bat" (
    echo [2/4] Initializing isolated virtual environment in .venv...
    python -m venv .venv
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created successfully.
) else (
    echo [2/4] Existing virtual environment found: .venv
)
echo.

:: 3. Activate virtual environment
echo [3/4] Activating virtual environment...
call .venv\Scripts\activate.bat

:: 4. Verify and install requirements
echo Checking and installing project dependencies from requirements.txt...
python -m pip install -r requirements.txt
if !ERRORLEVEL! NEQ 0 (
    echo [WARNING] Could not install all packages via requirements.txt.
)
echo Dependencies verified.
echo.

:: 5. Launch Streamlit Application
echo ============================================================================
echo [4/4] Launching GeoAI Streamlit Application...
echo The interface will open in your default browser shortly.
echo (Press CTRL+C in this console window to stop the server)
echo ============================================================================
echo.

python -m streamlit run app.py

:: Keep window open if the application exits with an error
if !ERRORLEVEL! NEQ 0 (
    echo.
    echo [NOTICE] Streamlit server stopped or exited with error code !ERRORLEVEL!.
    pause
)
