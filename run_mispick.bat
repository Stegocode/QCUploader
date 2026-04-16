@echo off
title QCUploader — Mispick Checker
color 0E
echo.
echo ============================================================
echo   QCUPLOADER — MISPICK CHECKER
echo   Standalone QC check against serial inventory export
echo ============================================================
echo.

set PYTHON=C:\Users\scottt\Documents\Python\WPy64-3.13.12.0\python\python.exe
set SCRIPT=%~dp0run_mispick.py

if "%~1"=="" (
    echo Usage: run_mispick.bat path\to\serial-number-inventory.csv
    echo.
    pause
    exit /b 1
)

echo Running mispick check against: %~1
echo.
%PYTHON% %SCRIPT% --serial "%~1"
echo.
echo Done.
pause
