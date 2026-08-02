@echo off
chcp 65001 >nul
set "VENV_DIR=venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

echo.
echo === AILibreTranslater ===
echo.
echo  1 - TUI (Textual interface)
echo  2 - Server (console)
echo.
set /p "CHOICE=Select mode [1-2] (default 1): "
if "%CHOICE%"=="2" goto server
if "%CHOICE%"=="" goto tui

:tui
call "%VENV_DIR%\Scripts\python" tui.py %*
goto end

:server
call "%VENV_DIR%\Scripts\python" main.py %*
goto end

:end
pause