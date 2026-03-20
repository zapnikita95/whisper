@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" (
    echo Не найден Python: %PY%
    pause
    exit /b 1
)

echo Запуск Whisper API сервера на GPU
echo.
echo Если используешь Tailscale, IP: http://100.115.68.2:8000
echo Или узнай локальный IP: ipconfig
echo.
echo Для остановки: Ctrl+C
echo.

"%PY%" "%~dp0whisper-server.py" --host 0.0.0.0 --port 8000
pause
