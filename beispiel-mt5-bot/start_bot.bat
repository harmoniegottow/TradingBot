@echo off
title MT5 Trading Bot
color 0A

echo ============================================================
echo   MT5 TRADING BOT - STARTER
echo ============================================================
echo.

rem In den Ordner wechseln, in dem diese Datei liegt
cd /d "%~dp0"

rem Pruefen ob bot.py da ist
if not exist bot.py (
    echo FEHLER: bot.py nicht gefunden!
    echo Diese Datei muss im mt5-bot-Ordner liegen - dort wo bot.py ist.
    echo.
    pause
    exit /b 1
)

rem Pruefen ob Python installiert ist
python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden!
    echo Bitte Python installieren oder PATH pruefen.
    echo.
    pause
    exit /b 1
)

echo Denk dran: MetaTrader 5 muss laufen und "Algo-Handel" gruen sein!
echo Stoppen: Strg + C  (SL/TP bleiben beim Broker aktiv)
echo.
echo Bot startet...
echo ------------------------------------------------------------
echo.

python bot.py

echo.
echo ------------------------------------------------------------
echo Bot wurde beendet.
pause
