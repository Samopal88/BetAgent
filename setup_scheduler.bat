@echo off
chcp 65001 > nul

echo Setting up BETAGENT scheduled tasks...

schtasks /create /tn "BETAGENT_Morning"   /tr "\"C:\betagent\run_betagent.bat\"" /sc daily /st 08:00 /f /rl highest
echo [OK] 08:00 morning

schtasks /create /tn "BETAGENT_Afternoon" /tr "\"C:\betagent\run_betagent.bat\"" /sc daily /st 14:00 /f /rl highest
echo [OK] 14:00 afternoon

schtasks /create /tn "BETAGENT_Evening"   /tr "\"C:\betagent\run_betagent.bat\"" /sc daily /st 21:00 /f /rl highest
echo [OK] 21:00 evening

schtasks /create /tn "BETAGENT_Night"     /tr "\"C:\betagent\run_betagent.bat\"" /sc daily /st 23:30 /f /rl highest
echo [OK] 23:30 night

schtasks /create /tn "BETAGENT_Bot"       /tr "pythonw \"C:\betagent\tg_bot.py\"" /sc onstart /f /rl highest
echo [OK] bot on startup

echo.
echo Done! Tasks registered.
schtasks /query /tn "BETAGENT*" /fo list 2>nul | findstr "Task Name\|Status\|Next Run"

pause
