@echo off
setlocal
title SPIDER AI
cd /d "%~dp0"

echo.
echo  SPIDER AI - document investigation
echo  ===================================
echo.

rem ---------------------------------------------------------------- first run: Python
if not exist "backend\.venv\Scripts\python.exe" (
  echo [setup] Creating the Python environment. This happens once, and takes a few minutes.
  python -m venv backend\.venv
  if errorlevel 1 (
    echo [error] Python 3 was not found on this computer. Install it from python.org, then run this file again.
    pause
    exit /b 1
  )
  backend\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  backend\.venv\Scripts\python.exe -m pip install --quiet -r backend\requirements.txt
  if errorlevel 1 (
    echo [error] Could not install the backend packages. Check your internet connection and run again.
    pause
    exit /b 1
  )
)

rem --------------------------------------------------------------- first run: interface
if not exist "frontend\node_modules" (
  echo [setup] Installing the interface. This happens once, and takes a few minutes.
  pushd frontend
  call npm install --no-audit --no-fund
  popd
)

rem The database starts empty - no demo accounts, no sample documents.
rem (backend/tools/seed_demo.py still exists if you ever want the sample set back.)

echo [run] Starting the analysis server in a separate window - leave it open.
start "SPIDER AI server" /min cmd /c "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [run] Waiting for the server...
timeout /t 4 /nobreak >nul

echo [run] Opening the workspace at http://localhost:5173
start "" http://localhost:5173

pushd frontend
call npm run dev
popd
endlocal
