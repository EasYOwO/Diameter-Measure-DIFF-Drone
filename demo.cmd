@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first.
  exit /b 1
)
".venv\Scripts\python.exe" examples\create_demo.py
if errorlevel 1 exit /b 1
call run.cmd --folder output\demo-input --output output\demo-results --non-interactive
