@echo off
title Deadlock WPA Overlay
cd /d "%~dp0"

echo ========================================================
echo   Deadlock WPA Overlay
echo ========================================================
echo  * Reads the live Statlocker recommendation row (1-5 cards)
echo  * Docked flush to the right edge, click-through in game
echo  * Background polling every 20 seconds
echo.
echo  Controls:
echo    F6  Cycle hero preview
echo    F7  Toggle "only during a match"
echo    F8  Toggle horizontal / vertical layout
echo    F9  Toggle lock (click-through) / move mode
echo    F10 Hide / show the overlay
echo    Tray icon: right-click for the same actions and Exit
echo ========================================================
echo.

uv run python main.py %*
if %ERRORLEVEL% NEQ 0 (
    python main.py %*
)
