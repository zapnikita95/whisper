@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Права администратора — для правила брандмауэра (как у start-server.bat)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Запрос прав администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b 0
)

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" (
    echo [ОШИБКА] Не найден Python: %PY%
    pause
    exit /b 1
)

echo Запуск окна сервера (порт, клиенты, подсказки по клавишам)...
"%PY%" "%~dp0whisper_server_gui.py"
if %errorlevel% neq 0 pause
