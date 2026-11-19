@echo off
echo ========================================================
echo Installing Gemini Antigravity Bridge Auto-Startup...
echo ========================================================

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_FILE=%STARTUP_FOLDER%\Start_Gemini_Antigravity_Bridge.vbs"
set "SCRIPT_DIR=%~dp0"

(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.Run "wscript.exe ""%SCRIPT_DIR%launch_bridge_silent.vbs""", 0, False
) > "%TARGET_FILE%"

echo [SUCCESS] Auto-Startup script registered at:
echo %TARGET_FILE%
echo.
echo Gemini Antigravity Bridge will now automatically launch silently on boot!
pause
