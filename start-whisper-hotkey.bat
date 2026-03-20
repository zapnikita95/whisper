@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Запрос прав администратора (нужен перехват клавиш). Если уже админ — сразу запуск.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Запрос прав администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b 0
)

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" (
    echo Не найден Python: %PY%
    echo См. README — установка venv.
    pause
    exit /b 1
)

echo Запуск голосового ввода ^(зажми Ctrl+Win — запись, отпусти — текст^)
echo Окно не закрывай. Выход: Ctrl+C
echo.

"%PY%" "%~dp0whisper-hotkey.py" %*
echo.
pause
