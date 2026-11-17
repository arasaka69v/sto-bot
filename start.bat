@echo off
chcp 65001 >nul
cd /d "%~dp0"
title СТО-бот
if not exist .venv\Scripts\python.exe (
    echo Бот ещё не установлен. Сначала запустите install.bat
    pause
    exit /b 1
)
if not exist .env (
    echo Нет файла настроек .env. Запустите install.bat
    pause
    exit /b 1
)
echo Запускаю бота. Не закрывайте это окно, пока бот нужен.
echo Остановить: Ctrl+C
echo.
.venv\Scripts\python.exe main.py
echo.
echo Бот остановлен. Если выше ошибка - сфотографируйте окно и пришлите.
pause
