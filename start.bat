@echo off
chcp 65001 >nul
set "VENV_DIR=venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

call "%VENV_DIR%\Scripts\python" main.py %*
pause
