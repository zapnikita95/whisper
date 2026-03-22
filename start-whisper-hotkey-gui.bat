@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Окно Whisper Hotkey (выбор модели + Ctrl+Win). Нужны права администратора для перехвата клавиш.
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

start "" "%PY%" "%~dp0whisper_hotkey_gui.py" %*
