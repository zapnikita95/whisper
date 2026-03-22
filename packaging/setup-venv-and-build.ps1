#Requires -Version 5.1
# Создаёт venv в %USERPROFILE%\.venvs\faster-whisper, ставит зависимости, собирает WhisperServer.exe.
# Запуск из любого каталога:
#   powershell -ExecutionPolicy Bypass -File "C:\путь\к\whisper\packaging\setup-venv-and-build.ps1"
$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvParent = Join-Path $env:USERPROFILE ".venvs"
$VenvDir = Join-Path $VenvParent "faster-whisper"
$Py = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "Repo:  $Repo"
Write-Host "Venv:  $VenvDir"
Write-Host ""

New-Item -ItemType Directory -Force -Path $VenvParent | Out-Null

if (-not (Test-Path $Py)) {
    Write-Host "Создаю venv..."
    python -m venv $VenvDir
} else {
    Write-Host "Venv уже есть, пропускаю python -m venv"
}

if (-not (Test-Path $Py)) {
    throw "Не найден $Py — проверь, что команда python в PATH (Python 3.10+)."
}

& $Py -m pip install -U pip
Set-Location $Repo
& $Py -m pip install -r .\requirements.txt
& $Py -m pip install pyinstaller

Write-Host ""
Write-Host "Запуск packaging\build-server-gui-exe.bat ..."
cmd.exe /c "packaging\build-server-gui-exe.bat"
