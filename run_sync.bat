@echo off
title QCUploader — Full Suite
color 0A
echo.
echo ============================================================
echo   QCUPLOADER — FULL SUITE
echo   Runs all day after morning populator
echo ============================================================
echo.

set PYTHON=C:\Users\scottt\Documents\Python\WPy64-3.13.12.0\python\python.exe
set SCRIPT=%~dp0sync.py

echo Starting sync loop...
echo Press Ctrl+C to stop
echo.
%PYTHON% %SCRIPT%
echo.
echo Sync stopped.
pause
