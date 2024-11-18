
@echo off
cd /d "C:\Vivek\coding\arleBot"

:: Kill any existing Python processes running the bot
if exist "C:\Vivek\coding\arleBot\bot.pid" (
    set /p BOT_PID=<"C:\Vivek\coding\arleBot\bot.pid"
    taskkill /F /PID %BOT_PID% /T > nul 2>&1
    del "C:\Vivek\coding\arleBot\bot.pid"
)

:: Additional cleanup of any remaining instances
taskkill /F /FI "WINDOWTITLE eq arleBot*" /T > nul 2>&1

:: Wait for processes to fully terminate
timeout /t 3 /nobreak > nul

:: Start the bot in a new window
start "arleBot" /MIN cmd /c "python "C:\Vivek\coding\arleBot\arleBot.py" & pause"

:: Exit the restart script
exit
