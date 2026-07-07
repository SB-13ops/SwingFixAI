@echo off
title SwingFix AI - Finding Python
color 0E

echo.
echo  Searching for Python on your computer...
echo  This may take 30-60 seconds.
echo.

set FOUND=0

REM Check py launcher
py -3 --version >nul 2>&1
if not errorlevel 1 (
    echo  FOUND via py launcher:
    where py
    set FOUND=1
)

REM Check PATH
python --version >nul 2>&1
if not errorlevel 1 (
    echo  FOUND on PATH:
    where python
    set FOUND=1
)

REM Check registry
echo.
echo  Checking Windows registry...
reg query "HKCU\Software\Python" >nul 2>&1
if not errorlevel 1 (
    echo  Registry entry found:
    reg query "HKCU\Software\Python\PythonCore" /s /v ExecutablePath 2>nul
)
reg query "HKLM\Software\Python" >nul 2>&1
if not errorlevel 1 (
    echo  System registry entry found:
    reg query "HKLM\Software\Python\PythonCore" /s /v ExecutablePath 2>nul
)

REM Brute force search
echo.
echo  Scanning common locations...
for %%V in (313 312 311 310 39) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        echo  FOUND: %LOCALAPPDATA%\Programs\Python\Python%%V\python.exe
        set FOUND=1
    )
)

echo.
echo  Deep scanning C drive (slow)...
dir /s /b "C:\python.exe" 2>nul | findstr /iv "store\|WindowsApps\|__pycache__"

echo.
if "%FOUND%"=="1" (
    echo  Python was found above.
    echo  Drag the python.exe path onto START.bat when it asks.
) else (
    echo  Python was NOT found anywhere.
    echo.
    echo  Please install it:
    echo   https://www.python.org/downloads/
    echo.
    echo  During install, CHECK "Add Python to PATH"
)
echo.
pause
