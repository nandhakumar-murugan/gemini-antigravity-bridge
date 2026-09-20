@echo off
title Gemini Live Desktop Companion (Project Astra Live Streamer)
color 0b
echo =====================================================================
echo       GEMINI LIVE DESKTOP COMPANION (PROJECT ASTRA SCREEN & VOICE)
echo =====================================================================
echo.
echo [1] Initializing screen capture (1 FPS live video stream)...
echo [2] Initializing microphone (16kHz PCM audio stream)...
echo [3] Initializing laptop speakers (24kHz native speech playback)...
echo [4] Connecting to Google Gemini Live API (gemini-2.5-flash-native-audio)...
echo.
echo Press Ctrl+C at any time to disconnect and stop streaming.
echo =====================================================================
echo.

python gemini_live_streamer.py

pause
