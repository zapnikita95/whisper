@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Desktop / Start Menu entry: always this repo (float16 + punctuation), never Program Files installer.
REM Use base pythonw + venv site-packages — venv Scripts\pythonw.exe is a stub that re-execs and
REM used to trip the single-instance mutex (second process exits immediately).

taskkill /F /IM WhisperHotkey.exe >nul 2>&1

powershell -NoProfile -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -match 'whisper_hotkey_tray') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

set "VENV=%USERPROFILE%\.venvs\faster-whisper"
set "PYW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYW%" set "PYW=%VENV%\Scripts\pythonw.exe"
if not exist "%PYW%" (
    echo Не найден Python: %PYW%
    echo См. README — установка venv.
    pause
    exit /b 1
)

set "PATH=%VENV%\Lib\site-packages\nvidia\cublas\bin;%VENV%\Scripts;%PATH%"
set "VIRTUAL_ENV=%VENV%"
set "PYTHONPATH=%~dp0;%VENV%\Lib\site-packages"
set "WHISPER_HOTKEY_SILENT_START=1"

start "" /D "%~dp0" "%PYW%" "%~dp0whisper_hotkey_tray.py" %*
