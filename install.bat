@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Установка СТО-бота
echo.
echo ===== Установка СТО-бота =====
echo.

rem --- 0. Путь к папке не должен быть длинным: у Windows лимит 260 символов ---
set "HERE=%~dp0"
if not "%HERE:~60,1%"=="" goto long_path

rem --- 1. Ищем Python: сначала через py, потом python ---
set "PY="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto no_python

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto old_python
for /f "delims=" %%v in ('%PY% --version') do echo Найден %%v

rem --- 2. Удаляем старую установку библиотек ---
if exist .venv (
    echo Удаляю старую папку .venv ...
    rmdir /s /q .venv
)
if exist .venv goto venv_locked

rem --- 3. Создаём окружение и ставим библиотеки ---
echo Создаю окружение .venv ...
%PY% -m venv .venv
if errorlevel 1 goto fail

echo Устанавливаю библиотеки, это 1-2 минуты ...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail

rem --- 4. Файл настроек .env: создаём, если его нет, старый не трогаем ---
if not exist .env (
    copy .env.example .env >nul
    echo Создан файл настроек .env
)

findstr /r /c:"^TELEGRAM_BOT_TOKEN=..*" .env >nul
if errorlevel 1 goto need_token
findstr /r /c:"^ADMIN_IDS=[0-9][0-9]*" .env >nul
if errorlevel 1 goto need_token

echo.
echo ===== Готово! =====
echo Если есть ключи Росско - запустите rossko_setup.bat
echo Запускайте бота файлом start.bat
echo.
pause
exit /b 0

:need_token
echo.
echo ===== Библиотеки установлены. Осталось заполнить настройки =====
echo Сейчас откроется Блокнот. Впишите после знака = без пробелов:
echo    TELEGRAM_BOT_TOKEN=  токен от @BotFather
echo    ADMIN_IDS=           ваш ID от @userinfobot
echo Затем нажмите Ctrl+S, закройте Блокнот и запустите start.bat
echo.
pause
notepad .env
exit /b 0

:long_path
echo ОШИБКА: папка с ботом лежит слишком глубоко:
echo %HERE%
echo У Windows есть лимит на длину пути, и библиотеки не установятся.
echo Скопируйте папку бота в C:\sto-bot и запустите install.bat оттуда.
pause
exit /b 1

:no_python
echo ОШИБКА: Python не найден.
echo Установите Python с python.org и поставьте галочку "Add Python to PATH".
echo После установки запустите install.bat ещё раз.
pause
exit /b 1

:old_python
echo ОШИБКА: нужен Python 3.11 или новее. Установите свежий с python.org.
pause
exit /b 1

:venv_locked
echo ОШИБКА: не получилось удалить папку .venv - наверное, бот сейчас запущен.
echo Закройте все чёрные окна с ботом и запустите install.bat ещё раз.
pause
exit /b 1

:fail
echo.
echo ОШИБКА при установке. Сфотографируйте это окно и пришлите.
pause
exit /b 1
