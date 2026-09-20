@echo off
title Gemini Live Desktop Companion & Floating Indicator
cd /d "%~dp0"
echo ========================================================
echo Starting Gemini Live Desktop Companion with Indicator...
echo - Screen Vision: 1 FPS continuous capture
echo - Voice Chat: Full duplex (16kHz mic, 24kHz speaker)
echo - Floating Indicator: Animated desktop pill
echo ========================================================
python -u gemini_live_streamer.py
pause
