@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."

REM Сборка WhisperHotkey.exe. cuBLAS-предупреждение в логе — из whisper_hotkey_core (входит в exe).
REM Проверка голоса: packaging\requirements-speaker-windows-pyi.txt + resemblyzer --no-deps (webrtcvad — заглушка в speaker_verify.py).
REM Используется WhisperHotkey.spec (collect-all torch/resemblyzer). Выход: dist\WhisperHotkey после переноса из .whisper_hotkey_stage.

set "STAGE=%CD%\dist\.whisper_hotkey_stage"
set "FINAL=%CD%\dist\WhisperHotkey"

set "PY=%USERPROFILE%\.venvs\faster-whisper\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/4] pip: CUDA DLL для exe ^(nvidia-cublas-cu12 из requirements.txt^) + speaker...
"%PY%" -m pip install -q "nvidia-cublas-cu12>=12.4.5.8"
"%PY%" -m pip install -q -r "%CD%\packaging\requirements-speaker-windows-pyi.txt"
if errorlevel 1 exit /b 1
"%PY%" -m pip install -q --no-deps "resemblyzer>=0.1.1"
if errorlevel 1 exit /b 1
"%PY%" -c "import speaker_verify; print('speaker_verify: import ok')"
if errorlevel 1 exit /b 1

echo [2/4] Закрой WhisperHotkey.exe (если запущен)...
taskkill /IM WhisperHotkey.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo [3/4] PyInstaller WhisperHotkey.spec ^(distpath=%STAGE%^)...
"%PY%" -m PyInstaller --noconfirm --clean ^
  --distpath "%STAGE%" ^
  --workpath "%CD%\build\WhisperHotkey" ^
  WhisperHotkey.spec
if errorlevel 1 exit /b 1

if not exist "%STAGE%\WhisperHotkey\WhisperHotkey.exe" (
  echo Не найден %STAGE%\WhisperHotkey\WhisperHotkey.exe
  exit /b 1
)

echo [4/4] Перенос в dist\WhisperHotkey ...
taskkill /IM WhisperHotkey.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
if exist "%FINAL%" rmdir /s /q "%FINAL%"
if exist "%FINAL%" (
  echo [ВНИМАНИЕ] Не удалось удалить "%FINAL%". Запуск: %STAGE%\WhisperHotkey\WhisperHotkey.exe
  goto :done
)
move "%STAGE%\WhisperHotkey" "%FINAL%" >nul
if errorlevel 1 (
  echo move не удался. Сборка: %STAGE%\WhisperHotkey\WhisperHotkey.exe
  goto :done
)
rmdir "%STAGE%" 2>nul
echo Готово: %FINAL%\WhisperHotkey.exe

:done
echo.
echo ============================================================
echo   ГДЕ EXE:
echo   • Нормально:  %FINAL%\WhisperHotkey.exe ^(вся папка dist\WhisperHotkey^)
echo   • Если перенос не вышел:  %STAGE%\WhisperHotkey\WhisperHotkey.exe
echo   • Вручную: packaging\promote-whisper-hotkey-dist.bat
echo   НЕ из build\ — только dist\
echo ============================================================
echo.
if not defined SKIP_BUILD_PAUSE pause
endlocal
