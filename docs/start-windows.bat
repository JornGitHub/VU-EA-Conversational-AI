@echo off
REM VU EA Conversational AI - dubbelklik dit bestand om de app te starten (Windows).
REM
REM Het startscript wordt eerst naar een tijdelijk bestand gedownload en daarna
REM gedraaid. Rechtstreeks vanaf internet uitvoeren (irm ... ^| iex) wordt op veel
REM bedrijfslaptops door de virusscanner geblokkeerd.
REM
REM Windows toont de eerste keer een SmartScreen-waarschuwing: klik op
REM "Meer informatie" en daarna op "Toch uitvoeren".
REM
REM Werkt dit niet? Gebruik dan de losse commando's op de projectpagina:
REM https://jorngithub.github.io/VU-EA-Conversational-AI/
title VU EA Conversational AI
set "SCRIPT=%TEMP%\vu-ea-start.ps1"
echo Startscript ophalen...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'https://jorngithub.github.io/VU-EA-Conversational-AI/start-windows.ps1' -OutFile '%SCRIPT%' -UseBasicParsing } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
  echo.
  echo Het startscript kon niet worden gedownload.
  echo Gebruik de losse commando's op https://jorngithub.github.io/VU-EA-Conversational-AI/
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
echo.
echo De app is gestopt. Druk op een toets om dit venster te sluiten.
pause >nul
