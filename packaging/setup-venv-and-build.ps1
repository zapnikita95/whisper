#Requires -Version 5.1
# Venv + зависимости + опционально скачать модели + сборка exe.
#
# Только venv и pip:
#   powershell -ExecutionPolicy Bypass -File "...\packaging\setup-venv-and-build.ps1" -Build None
#
# Сборка сервера (WhisperServer.exe):
#   powershell -ExecutionPolicy Bypass -File "...\packaging\setup-venv-and-build.ps1" -Build Server
#
# Сборка hotkey (WhisperHotkey.exe, трей):
#   powershell -ExecutionPolicy Bypass -File "...\packaging\setup-venv-and-build.ps1" -Build Hotkey
#
# Оба + скачать все пресеты в кэш HF (долго, нужен интернет):
#   powershell -ExecutionPolicy Bypass -File "...\packaging\setup-venv-and-build.ps1" -Build Both -DownloadModels
param(
    [ValidateSet("None", "Server", "Hotkey", "Both")]
    [string] $Build = "Both",
    [switch] $DownloadModels
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvParent = Join-Path $env:USERPROFILE ".venvs"
$VenvDir = Join-Path $VenvParent "faster-whisper"
$Py = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "Repo:  $Repo"
Write-Host "Venv:  $VenvDir"
Write-Host "Build: $Build  |  DownloadModels: $DownloadModels"
Write-Host ""

New-Item -ItemType Directory -Force -Path $VenvParent | Out-Null

if (-not (Test-Path $Py)) {
    Write-Host "Создаю venv..."
    python -m venv $VenvDir
} else {
    Write-Host "Venv уже есть."
}

if (-not (Test-Path $Py)) {
    throw "Не найден $Py — нужен Python 3.10+ в PATH."
}

& $Py -m pip install -U pip
Set-Location $Repo
& $Py -m pip install -r .\requirements.txt
& $Py -m pip install pyinstaller

if ($DownloadModels) {
    Write-Host ""
    Write-Host "Скачивание пресетов в кэш Hugging Face (scripts\download_whisper_models.py)..."
    & $Py .\scripts\download_whisper_models.py
    if ($LASTEXITCODE -ne 0) {
        throw "download_whisper_models.py завершился с ошибкой."
    }
}

function Invoke-ServerBuild {
    Write-Host ""
    Write-Host ">>> packaging\build-server-gui-exe.bat"
    cmd.exe /c "packaging\build-server-gui-exe.bat"
}

function Invoke-HotkeyBuild {
    Write-Host ""
    Write-Host ">>> packaging\build-hotkey-gui-exe.bat"
    cmd.exe /c "packaging\build-hotkey-gui-exe.bat"
}

switch ($Build) {
    "None" { }
    "Server" { Invoke-ServerBuild }
    "Hotkey" { Invoke-HotkeyBuild }
    "Both" {
        Invoke-ServerBuild
        Invoke-HotkeyBuild
    }
}

Write-Host ""
Write-Host "========== КУДА ЖАТЬ ==========" -ForegroundColor Yellow
Write-Host "Сервер:  $Repo\dist\WhisperServer\WhisperServer.exe"
Write-Host "Hotkey:   $Repo\dist\WhisperHotkey\WhisperHotkey.exe"
Write-Host "НЕ открывай exe из папки build\ — там служебные файлы PyInstaller, запуск ломается."
Write-Host "================================"
