@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Desktop / Start Menu entry: always this repo (float16 + punctuation), never Program Files installer.

taskkill /F /IM WhisperHotkey.exe >nul 2>&1

powershell -NoProfile -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'whisper_hotkey_tray\.py') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

set "PYW=%USERPROFILE%\.venvs\faster-whisper\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PYW%" (
    echo Не найден Python: %USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe
    echo См. README — установка venv.
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0whisper_hotkey_tray.py" %*
