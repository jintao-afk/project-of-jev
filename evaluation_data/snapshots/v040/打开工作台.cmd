@echo off
setlocal
set "JEV_LAUNCHER_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%JEV_LAUNCHER_PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0open.ps1" %*
set "JEV_LAUNCHER_EXIT=%ERRORLEVEL%"
if not "%JEV_LAUNCHER_EXIT%"=="0" (
    echo.
    echo Startup failed. Check logs\launcher.log and logs\server.stderr.log.
    if /I not "%~1"=="-CheckOnly" pause
)
exit /b %JEV_LAUNCHER_EXIT%
