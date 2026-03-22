@echo off
chcp 65001 >nul
cd /d "%~dp0.."

REM Сборка WhisperHotkey.exe (окно без консоли). Нужен venv с faster-whisper и pip install pyinstaller

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "ICONLINE="
if exist "assets\app_icon.ico" set "ICONLINE=--icon assets\app_icon.ico"
set "ICODATA="
if exist "assets\app_icon.ico" set "ICODATA=--add-data assets\app_icon.ico;assets"

REM Проверка голоса в exe: в venv сначала pip install -r requirements-speaker.txt (torch + resemblyzer).
"%PY%" -m PyInstaller --noconfirm --clean --windowed --name WhisperHotkey ^
  %ICONLINE% ^
  --hidden-import whisper_hotkey_core --hidden-import whisper_hotkey_tray ^
  --hidden-import whisper_models --hidden-import whisper_file_log ^
  --hidden-import speaker_verify ^
  --hidden-import faster_whisper --hidden-import whisper_version ^
  --hidden-import keyboard --hidden-import pyaudio --hidden-import pyperclip ^
  --hidden-import soundfile --hidden-import numpy ^
  --hidden-import plyer.platforms.win.notification ^
  --hidden-import pystray --hidden-import PIL --hidden-import PIL.Image ^
  --add-data "packaging\VERSION;packaging" ^
  %ICODATA% ^
  whisper_hotkey_tray.py

echo.
echo ============================================================
echo   ВАЖНО: запускай ТОЛЬКО отсюда ^(вся папка dist\WhisperHotkey^):
echo   %CD%\dist\WhisperHotkey\WhisperHotkey.exe
echo.
echo   НЕ запускай exe из папки build\ — ошибка Python DLL.
echo ============================================================
echo.
pause
