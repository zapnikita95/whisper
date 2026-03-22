#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAC="$ROOT/packaging/mac"
APP="$MAC/WhisperClient.app"

echo "Сборка $APP …"
mkdir -p "$APP/Contents/Resources"
cp -f "$ROOT/whisper-client-mac.py" "$APP/Contents/Resources/"
cp -f "$MAC/pick_server_url.py" "$APP/Contents/Resources/"
cp -f "$MAC/launcher.sh" "$APP/Contents/MacOS/WhisperClient"
chmod +x "$APP/Contents/MacOS/WhisperClient"
echo "Готово. Перетащи WhisperClient.app в Программы."
echo "Нужны: Python 3 с pynput, requests, sounddevice, … (как в README)."
