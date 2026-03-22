@echo off
REM Перенос dist\.whisper_hotkey_stage\WhisperHotkey → dist\WhisperHotkey
setlocal
cd /d "%~dp0.."
set "STAGE=%CD%\dist\.whisper_hotkey_stage\WhisperHotkey"
set "FINAL=%CD%\dist\WhisperHotkey"

if not exist "%STAGE%\WhisperHotkey.exe" (
  echo Нет сборки: %STAGE%\WhisperHotkey.exe
  exit /b 1
)

taskkill /IM WhisperHotkey.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%FINAL%" rmdir /s /q "%FINAL%"
if exist "%FINAL%" (
  echo Не удалось удалить %FINAL%. Запускай: %STAGE%\WhisperHotkey.exe
  exit /b 1
)

move "%STAGE%" "%FINAL%" >nul
if errorlevel 1 (
  echo move не удался.
  exit /b 1
)

rmdir "%CD%\dist\.whisper_hotkey_stage" 2>nul
echo OK — запускай только: %FINAL%\WhisperHotkey.exe
endlocal
