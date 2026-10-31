@echo off
rem Start MarketPulse when you log in to Windows, or stop doing so.
rem   automation\autostart.bat on
rem   automation\autostart.bat off
rem This only adds or removes one small file in your Windows Startup folder.

if not defined STARTUP_FOLDER set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK=%STARTUP_FOLDER%\MarketPulse.bat"

if /i "%~1"=="on" (
    > "%LINK%" echo @call "%~dp0..\run_marketpulse.bat"
    echo MarketPulse will start when you log in.
    exit /b 0
)
if /i "%~1"=="off" (
    if exist "%LINK%" del "%LINK%"
    echo MarketPulse will no longer start when you log in.
    exit /b 0
)
echo Use: automation\autostart.bat on   or   automation\autostart.bat off
exit /b 1
