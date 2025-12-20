@echo off
setlocal

REM --------------------------------------------------
REM Git History Synth – UI Launcher
REM --------------------------------------------------

REM Change to the directory where this script lives
cd /d "%~dp0"

REM Optional: activate virtual environment if present
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM Check Python
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python not found.
    echo Please install Python or ensure .venv is present.
    echo.
    pause
    exit /b 1
)

REM Apply migrations silently (safe even if already applied)
"%PYTHON%" manage.py migrate >nul 2>&1

REM Start Django server
echo.
echo Starting Git History Synth UI...
echo Open http://127.0.0.1:8000/ in your browser
echo Press CTRL+C to stop the server
echo.

REM Open browser after short delay
start "" http://127.0.0.1:8000/

"%PYTHON%" manage.py runserver 127.0.0.1:8000

endlocal
pause
