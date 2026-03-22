@echo off
REM Перенос dist\.whisper_stage\WhisperServer → dist\WhisperServer
REM (после pyinstaller WhisperServer.spec, если финальный move не делался автоматически)
setlocal
cd /d "%~dp0.."
set "STAGE=%CD%\dist\.whisper_stage\WhisperServer"
set "FINAL=%CD%\dist\WhisperServer"

if not exist "%STAGE%\WhisperServer.exe" (
  echo Нет сборки: %STAGE%\WhisperServer.exe
  exit /b 1
)

taskkill /IM WhisperServer.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%FINAL%" rmdir /s /q "%FINAL%"
if exist "%FINAL%" (
  echo Не удалось удалить %FINAL%. Запускай: %STAGE%\WhisperServer.exe
  exit /b 1
)

move "%STAGE%" "%FINAL%" >nul
if errorlevel 1 (
  echo move не удался.
  exit /b 1
)

rmdir "%CD%\dist\.whisper_stage" 2>nul
echo OK: %FINAL%\WhisperServer.exe
endlocal
