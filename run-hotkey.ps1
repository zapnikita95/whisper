# Запуск whisper-hotkey.py через venv.
$VenvPython = "$env:USERPROFILE\.venvs\faster-whisper\Scripts\python.exe"
$Script = Join-Path $PSScriptRoot "whisper-hotkey.py"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Нет интерпретатора: $VenvPython — см. README, раздел Установка."
    exit 1
}
& $VenvPython $Script @args
