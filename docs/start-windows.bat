@echo off
REM VU EA Conversational AI - dubbelklik dit bestand om de app te starten (Windows).
REM
REM Windows toont de eerste keer een SmartScreen-waarschuwing: klik op
REM "Meer informatie" en daarna op "Toch uitvoeren".
title VU EA Conversational AI
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://jorngithub.github.io/VU-EA-Conversational-AI/start-windows.ps1 | iex"
echo.
echo De app is gestopt. Druk op een toets om dit venster te sluiten.
pause >nul
