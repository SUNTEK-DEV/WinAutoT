@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ and retry.
  pause
  exit /b 1
)
python build.py
set ERR=%ERRORLEVEL%
if not %ERR%==0 (
  echo.
  echo Build failed, exit code %ERR%.
)
pause
exit /b %ERR%
