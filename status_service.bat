@echo off
echo ========================================================
echo Gemini Antigravity Bridge Service Status
echo ========================================================

set "TARGET_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Start_Gemini_Antigravity_Bridge.vbs"

if exist "%TARGET_FILE%" (
    echo [STARTUP STATUS]: ENABLED [Registered in Windows Startup]
) else (
    echo [STARTUP STATUS]: DISABLED [Not registered in Startup]
)

echo.
echo [PORT 8000 STATUS]:
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess"

echo.
echo [HTTP HEALTH CHECK]:
powershell -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 3; Write-Host '[HEALTH]: 200 OK (' $r.service ')' -ForegroundColor Green } catch { Write-Host '[HEALTH]: Offline / Error' -ForegroundColor Red }"

echo.
echo [WATCHDOG LOG (Last 5 lines)]:
if exist "%~dp0watchdog.log" (
    powershell -Command "Get-Content '%~dp0watchdog.log' -Tail 5"
) else (
    echo No watchdog.log found yet.
)
