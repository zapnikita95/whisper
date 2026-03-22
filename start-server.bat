@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ╔══════════════════════════════════════════╗
echo ║   Whisper GPU Server — для Mac клиента   ║
echo ╚══════════════════════════════════════════╝
echo.

REM Запрос прав администратора
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

REM Находим свободный порт начиная с 8000
for /f %%p in ('powershell -NoProfile -Command "$port=8000; while((Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue)) { $port++ }; $port"') do set "PORT=%%p"

REM Открываем найденный порт в брандмауэре
netsh advfirewall firewall show rule name="Whisper Server %PORT%" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="Whisper Server %PORT%" dir=in action=allow protocol=TCP localport=%PORT% >nul
)

REM Сохраняем порт в файл, чтобы client-mac.command мог его прочитать
echo %PORT% > "%~dp0server_port.txt"

echo ┌─────────────────────────────────────────┐
echo │  Mac: возьми IPv4 ЭТОГО ПК в Tailscale  │
echo │  (IP бывает другим, не копируй слепо).   │
echo │                                         │
echo │  start-client-mac.command "http://IP:%PORT%" │
echo │  или server_url.txt / WHISPER_SERVER_IP │
echo └─────────────────────────────────────────┘
echo.
echo Для остановки: Ctrl+C
echo.

"%PY%" "%~dp0whisper-server.py" --host 0.0.0.0 --port %PORT%

echo.
pause
