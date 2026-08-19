@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "VENV_DIR=venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create venv. Make sure Python 3.10+ is installed.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists, skipping...
)

echo [2/3] Installing dependencies...
call "%VENV_DIR%\Scripts\pip" install -r requirements.txt
if !errorlevel! neq 0 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [3/4] Creating .env from .env.example...
    copy .env.example .env >nul
    echo   - Don't forget to edit .env with your API keys!
) else (
    echo [3/4] .env already exists, skipping...
)

if not exist "config.json" (
    echo [4/4] Creating config.json from config.json.example...
    copy config.json.example config.json >nul
    echo   - Edit config.json to customize your local setup.
) else (
    echo [4/4] config.json already exists, skipping...
)

echo.
echo Done! Run start.bat to start the server.
pause
