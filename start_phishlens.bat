@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua co moi truong .venv. Hay lam theo README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" launch.py %*
if errorlevel 1 pause
