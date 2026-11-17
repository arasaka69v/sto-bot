@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Настройка Росско
if not exist .venv\Scripts\python.exe (
    echo Бот ещё не установлен. Сначала запустите install.bat
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m stobot.rossko_setup
echo.
pause
