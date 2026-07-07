@echo off
title SwingFix AI
color 0A

echo.
echo  ============================================
echo   SwingFix AI - Starting Up
echo  ============================================
echo.

set PYTHON=

REM --- Try the most common options first ---
py -3 --version >nul 2>&1
if not errorlevel 1 ( set PYTHON=py -3 & goto :found )

python --version >nul 2>&1
if not errorlevel 1 ( set PYTHON=python & goto :found )

python3 --version >nul 2>&1
if not errorlevel 1 ( set PYTHON=python3 & goto :found )

REM --- Try common install paths directly ---
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" ( set PYTHON="%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto :found )
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" ( set PYTHON="%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto :found )
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" ( set PYTHON="%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto :found )
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" ( set PYTHON="%LOCALAPPDATA%\Programs\Python\Python310\python.exe" & goto :found )
if exist "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"  ( set PYTHON="%LOCALAPPDATA%\Programs\Python\Python39\python.exe"  & goto :found )
if exist "C:\Python313\python.exe" ( set PYTHON="C:\Python313\python.exe" & goto :found )
if exist "C:\Python312\python.exe" ( set PYTHON="C:\Python312\python.exe" & goto :found )
if exist "C:\Python311\python.exe" ( set PYTHON="C:\Python311\python.exe" & goto :found )
if exist "C:\Python310\python.exe" ( set PYTHON="C:\Python310\python.exe" & goto :found )
if exist "C:\Python39\python.exe"  ( set PYTHON="C:\Python39\python.exe"  & goto :found )
if exist "C:\Program Files\Python313\python.exe" ( set PYTHON="C:\Program Files\Python313\python.exe" & goto :found )
if exist "C:\Program Files\Python312\python.exe" ( set PYTHON="C:\Program Files\Python312\python.exe" & goto :found )
if exist "C:\Program Files\Python311\python.exe" ( set PYTHON="C:\Program Files\Python311\python.exe" & goto :found )
if exist "C:\Program Files\Python310\python.exe" ( set PYTHON="C:\Program Files\Python310\python.exe" & goto :found )

REM --- Ask PowerShell to find it (works even without PATH) ---
echo  Checking with PowerShell...
for /f "delims=" %%P in ('powershell -NoProfile -Command "Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source" 2^>nul') do (
    if exist "%%P" ( set PYTHON="%%P" & goto :found )
)
for /f "delims=" %%P in ('powershell -NoProfile -Command "(Get-Item (Get-ItemProperty HKCU:\Software\Python\PythonCore\* -ErrorAction SilentlyContinue | Select-Object -ExpandProperty '(default)' | Select-Object -First 1) -ErrorAction SilentlyContinue).FullName" 2^>nul') do (
    if exist "%%P\python.exe" ( set PYTHON="%%P\python.exe" & goto :found )
)

REM --- Last resort: ask the user ---
echo.
echo  Could not find Python automatically.
echo.
echo  OPTIONS:
echo   A) Open File Explorer, find python.exe, and DRAG it
echo      onto this window, then press Enter.
echo.
echo   B) Install Python:
echo      1. Go to https://www.python.org/downloads/
echo      2. Download and run the installer
echo      3. CHECK the box "Add Python to PATH"
echo      4. Close and re-open this file
echo.
set /p PYTHON="Drag python.exe here (or press Enter to exit): "
if "%PYTHON%"=="" ( pause & exit /b 1 )

:found
echo  Found: %PYTHON%
%PYTHON% --version
echo.

REM ============================================================
REM --- API Key ---
REM ============================================================
if not "%ANTHROPIC_API_KEY%"=="" goto :have_key

echo  --------------------------------------------
echo   OPTIONAL: Anthropic API key for AI-written coaching
echo   (get one at https://console.anthropic.com)
echo.
echo   No key? Just press Enter - the app still does full
echo   video analysis, skeleton overlay, scores, and drills
echo   using its built-in coaching engine.
echo  --------------------------------------------
echo.
set /p ANTHROPIC_API_KEY="  Paste key or press Enter to skip: "
echo.

:have_key
if "%ANTHROPIC_API_KEY%"=="" (
    echo  Running without API key - built-in coaching engine active.
) else (
    echo  API key accepted - AI coaching enabled.
)
echo.

REM ============================================================
REM --- Setup virtual environment ---
REM ============================================================
cd /d "%~dp0backend"

if not exist "venv\" (
    echo  First-time setup: installing Python packages...
    echo  This takes 2-5 minutes and only happens once.
    echo.
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo.
        echo  ERROR: Could not create virtual environment.
        echo  Try: right-click START.bat and choose "Run as administrator"
        pause & exit /b 1
    )
    call venv\Scripts\activate.bat
    venv\Scripts\python -m pip install --quiet --upgrade pip
    venv\Scripts\python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  ERROR: Package install failed.
        echo  Check your internet connection and try again.
        pause & exit /b 1
    )
    echo.
    echo  Setup complete!
    echo.
) else (
    call venv\Scripts\activate.bat
)

REM ============================================================
REM --- Kill anything on port 8000 ---
REM ============================================================
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /f /pid %%a >nul 2>&1
)

REM ============================================================
REM --- Start the server ---
REM ============================================================
echo  Starting SwingFix AI server...
start "SwingFix Backend" /b venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000

REM --- Wait until server responds (try every second, up to 30s) ---
echo  Waiting for server to be ready...
set /a TRIES=0
:wait_loop
set /a TRIES+=1
if %TRIES% gtr 30 (
    echo  Server took too long to start. Check for errors above.
    pause & exit /b 1
)
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "try { (Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing -TimeoutSec 1).StatusCode } catch { exit 1 }" >nul 2>&1
if errorlevel 1 goto :wait_loop

REM ============================================================
REM --- Open browser ---
REM ============================================================
echo  Opening SwingFix AI in your browser...
start "" "http://127.0.0.1:8000"

echo.
echo  ============================================
echo   SwingFix AI is running!
echo   Opened: http://127.0.0.1:8000
echo.
echo   Keep this window open while using the app.
echo   Close this window to stop the server.
echo  ============================================
echo.
pause
