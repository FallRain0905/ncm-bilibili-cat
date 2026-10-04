@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "FORMAT=%~1"
if not defined FORMAT set "FORMAT=flac"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0转换.ps1" -Format "%FORMAT%"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" echo Conversion finished with errors. See messages above.
pause
exit /b %RESULT%
