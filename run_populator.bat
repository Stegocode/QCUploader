@echo off
title QCUploader — Morning Populator
color 0B
echo.
echo ============================================================
echo   QCUPLOADER — MORNING POPULATOR
echo   Run this once before starting the sync
echo ============================================================
echo.

set PYTHON=C:\Users\scottt\Documents\Python\WPy64-3.13.12.0\python\python.exe
set SCRIPT=%~dp0run_populator.py

echo Running populator...
echo.
%PYTHON% %SCRIPT%
echo.
echo Done. You can now start run_sync.bat
pause
