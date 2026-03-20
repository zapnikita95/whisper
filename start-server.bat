@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ╔══════════════════════════════════════════╗
echo ║   Whisper GPU Server — для Mac клиента   ║
echo ╚══════════════════════════════════════════╝
echo.

REM Запрос прав администратора (нужен для открытия порта в брандмауэре)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Запрос прав администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b 0
)

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" (
    echo [ОШИБКА] Не найден Python: %PY%
    echo Установи venv согласно README.
    pause
    exit /b 1
)

REM Открываем порт 8000 в брандмауэре (если правило ещё не создано)
netsh advfirewall firewall show rule name="Whisper Server 8000" >nul 2>&1
if %errorlevel% neq 0 (
    echo Открываю порт 8000 в брандмауэре...
    netsh advfirewall firewall add rule name="Whisper Server 8000" dir=in action=allow protocol=TCP localport=8000 >nul
    echo Порт 8000 открыт.
) else (
    echo Порт 8000 уже открыт.
)

echo.
echo Сервер доступен с Мака по адресу:
echo   http://100.115.68.2:8000
echo.
echo Запуск сервера... (модель загрузится при первом запросе)
echo Для остановки: Ctrl+C
echo.

"%PY%" "%~dp0whisper-server.py" --host 0.0.0.0 --port 8000

echo.
pause
