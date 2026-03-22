@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

REM Сборка WhisperServer.exe (окно без консоли). Нужен: pip install pyinstaller
REM Запускать из venv с faster-whisper / fastapi / uvicorn.
REM
REM WinError 5 при удалении dist\WhisperServer: закрой WhisperServer.exe и окно Проводника
REM в этой папке. Сборка идёт в dist\.whisper_stage, затем move в dist\WhisperServer.

set "STAGE=%CD%\dist\.whisper_stage"
set "WORK=%CD%\build\WhisperServer"
set "FINAL=%CD%\dist\WhisperServer"

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "ICONLINE="
if exist "assets\app_icon.ico" set "ICONLINE=--icon assets\app_icon.ico"

echo.
echo --- Закрой WhisperServer.exe и не держи открытой папку dist\WhisperServer в Проводнике ---
echo.
taskkill /IM WhisperServer.exe /F >nul 2>&1
REM ~2 с без timeout: из PowerShell cmd /c без TTY даёт "Input redirection is not supported"
ping 127.0.0.1 -n 3 >nul

"%PY%" -m PyInstaller --noconfirm --clean --windowed --name WhisperServer ^
  --distpath "%STAGE%" ^
  --workpath "%WORK%" ^
  %ICONLINE% ^
  --collect-all uvicorn --collect-all fastapi --collect-all starlette ^
  --hidden-import whisper_server --hidden-import whisper_models --hidden-import whisper_file_log ^
  --hidden-import faster_whisper ^
  --hidden-import whisper_version --hidden-import whisper_update_check ^
  --add-data "packaging\VERSION;packaging" ^
  whisper_server_gui.py

if errorlevel 1 (
  echo.
  echo PyInstaller завершился с ошибкой.
  goto :finish
)

if not exist "%STAGE%\WhisperServer\WhisperServer.exe" (
  echo.
  echo Не найден %STAGE%\WhisperServer\WhisperServer.exe
  goto :finish
)

echo.
echo Перенос сборки в dist\WhisperServer ...
taskkill /IM WhisperServer.exe /F >nul 2>&1
REM ~2 с без timeout: из PowerShell cmd /c без TTY даёт "Input redirection is not supported"
ping 127.0.0.1 -n 3 >nul

if exist "%FINAL%" rmdir /s /q "%FINAL%"
if exist "%FINAL%" (
  echo.
  echo [ВНИМАНИЕ] Не удалось удалить "%FINAL%" — файлы заняты ^(exe, антивирус, OneDrive^).
  echo Запускай сборку отсюда, пока не освободишь папку:
  echo   %STAGE%\WhisperServer\WhisperServer.exe
  goto :finish
)

move "%STAGE%\WhisperServer" "%FINAL%" >nul
if errorlevel 1 (
  echo move не удался. Сборка: %STAGE%\WhisperServer\WhisperServer.exe
  goto :finish
)
rmdir "%STAGE%" 2>nul

echo Готово: %FINAL%\WhisperServer.exe

:finish
echo.
echo ============================================================
echo   ВАЖНО: запускай ТОЛЬКО отсюда ^(вместе с папкой _internal^):
echo   %FINAL%\WhisperServer.exe
echo.
echo   НЕ запускай exe из папки build\ — там неполная сборка,
echo   будет ошибка "Failed to load Python DLL".
echo.
echo   Если COLLECT падал с WinError 5: закрой WhisperServer.exe,
echo   закрой Проводник в dist\WhisperServer, повтори сборку.
echo ============================================================
echo.
REM nopause — когда скрипт дергают из setup-venv-and-build.ps1 / CI
if /i not "%~1"=="nopause" pause
endlocal
