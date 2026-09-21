@echo off
setlocal
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist logs mkdir logs
if exist ".venv\Scripts\python.exe" (
  set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
  set "PYTHON_BIN=python"
)
"%PYTHON_BIN%" run_pipeline.py --now >> logs\pipeline.log 2>&1
exit /b %errorlevel%
