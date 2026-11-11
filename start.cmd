@echo off
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "FLIGHTDECK_LAUNCH_EXIT=%ERRORLEVEL%"
if not "%FLIGHTDECK_LAUNCH_EXIT%"=="0" (
  echo.
  echo Flightdeck could not start. Read the error above.
)
pause
exit /b %FLIGHTDECK_LAUNCH_EXIT%
