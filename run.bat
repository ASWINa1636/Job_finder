@echo off
title Local AI Job Finder - Desktop Edition
cd /d "%~dp0"

echo ========================================================
echo   Local AI Job Finder - Tkinter Desktop Edition
echo ========================================================
echo.

if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" app.py
    goto end
)

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    py app.py
    goto end
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python app.py
    goto end
)

echo [ERROR] Python not found on PATH or standard install directories.
echo Please install Python 3.10+ and add it to PATH.
pause

:end

