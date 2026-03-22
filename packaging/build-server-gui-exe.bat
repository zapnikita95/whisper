@echo off
chcp 65001 >nul
cd /d "%~dp0.."

REM Сборка WhisperServer.exe (окно без консоли). Нужен: pip install pyinstaller
REM Запускать из venv с faster-whisper / fastapi / uvicorn.

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

REM После cd корень репо — иконка без пробелов в пути
set "ICONLINE="
if exist "assets\app_icon.ico" set "ICONLINE=--icon assets\app_icon.ico"

"%PY%" -m PyInstaller --noconfirm --clean --windowed --name WhisperServer ^
  %ICONLINE% ^
  --collect-all uvicorn --collect-all fastapi --collect-all starlette ^
  --hidden-import whisper_server --hidden-import whisper_models --hidden-import whisper_file_log ^
  --hidden-import faster_whisper ^
  --hidden-import whisper_version --hidden-import whisper_update_check ^
  --add-data "packaging\VERSION;packaging" ^
  whisper_server_gui.py

echo.
echo ============================================================
echo   ВАЖНО: запускай ТОЛЬКО отсюда ^(вместе с папкой _internal^):
echo   %CD%\dist\WhisperServer\WhisperServer.exe
echo.
echo   НЕ запускай exe из папки build\ — там неполная сборка,
echo   будет ошибка "Failed to load Python DLL".
echo ============================================================
echo.
pause
