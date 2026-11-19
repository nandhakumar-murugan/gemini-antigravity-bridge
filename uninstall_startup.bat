@echo off
echo ========================================================
echo Removing Gemini Antigravity Bridge Auto-Startup...
echo ========================================================

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_FILE=%STARTUP_FOLDER%\Start_Gemini_Antigravity_Bridge.vbs"

if exist "%TARGET_FILE%" (
    del "%TARGET_FILE%"
    echo [SUCCESS] Auto-Startup script removed successfully.
) else (
    echo [INFO] Auto-Startup script was not found.
)

pause
