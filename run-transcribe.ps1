# Запуск transcribe.py через venv вне OneDrive (см. README).
$VenvPython = "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe"
$Script = Join-Path $PSScriptRoot "transcribe.py"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Нет интерпретатора: $VenvPython — см. README, раздел Установка."
    exit 1
}
& $VenvPython $Script @args
