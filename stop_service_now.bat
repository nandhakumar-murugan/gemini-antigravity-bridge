@echo off
echo Stopping Gemini Antigravity Bridge and Watchdog...

powershell -Command "Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*bridge_watchdog*' -or $_.CommandLine -like '*run_with_tunnel*' } | Stop-Process -Force -ErrorAction SilentlyContinue"
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

echo [DONE] Bridge stopped.
pause
