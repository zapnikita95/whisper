@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "%~dp0WhisperHotkey.exe" (
    start "" "%~dp0WhisperHotkey.exe" --settings
) else if exist "%ProgramFiles%\Whisper Hotkey\WhisperHotkey.exe" (
    start "" "%ProgramFiles%\Whisper Hotkey\WhisperHotkey.exe" --settings
) else (
    set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
    if exist "%PY%" (
        start "" "%PY%" "%~dp0whisper_hotkey_tray.py" --settings
    ) else (
        echo Whisper Hotkey not found. Install from GitHub releases.
        pause
    )
)
