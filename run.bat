@echo off
cd /d "%~dp0"
if exist "WinAutoTest.exe" (
  start "" "%~dp0WinAutoTest.exe"
  exit /b 0
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
) else (
  python main.py
)
if errorlevel 1 pause
