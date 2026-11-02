@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,13) else 1)"
if errorlevel 1 (
  echo Install 64-bit Python 3.13 and recreate .venv before setup.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if errorlevel 1 exit /b 1
echo Setup complete. Run run.cmd --help or demo.cmd
