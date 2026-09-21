@echo off
setlocal
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
REM TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be provided in .env.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
  set "PYTHON_BIN=python"
)
:loop
echo Starting bot...
"%PYTHON_BIN%" tg_bot.py
echo Bot stopped, restarting in 30 sec...
timeout /t 30 /nobreak > nul
goto loop
