@echo off
chcp 65001 >nul
cd /d "%~dp0.."

REM Сборка WhisperHotkey.exe (окно без консоли). Нужен venv с faster-whisper и pip install pyinstaller

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "ICONLINE="
if exist "assets\app_icon.ico" set "ICONLINE=--icon assets\app_icon.ico"

"%PY%" -m PyInstaller --noconfirm --clean --windowed --name WhisperHotkey ^
  %ICONLINE% ^
  --hidden-import whisper_hotkey_core --hidden-import whisper_models ^
  --hidden-import faster_whisper --hidden-import whisper_version ^
  --hidden-import keyboard --hidden-import pyaudio --hidden-import pyperclip ^
  --hidden-import soundfile --hidden-import numpy ^
  --add-data "packaging\VERSION;packaging" ^
  whisper_hotkey_gui.py

echo.
echo Готово: dist\WhisperHotkey\WhisperHotkey.exe (рядом _internal)
pause
