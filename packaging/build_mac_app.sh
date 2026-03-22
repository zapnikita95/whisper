#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAC="$ROOT/packaging/mac"
APP="$MAC/WhisperClient.app"

echo "Сборка $APP …"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -f "$MAC/Info.plist.template" "$APP/Contents/Info.plist"
cp -f "$ROOT/whisper-client-mac.py" "$APP/Contents/Resources/"
cp -f "$MAC/pick_server_url.py" "$APP/Contents/Resources/"
cp -f "$MAC/run.sh" "$APP/Contents/MacOS/run.sh"
chmod +x "$APP/Contents/MacOS/run.sh"

if ! xcrun clang -O2 -Wall -Wextra -o "$APP/Contents/MacOS/WhisperClient" "$MAC/whisper_stub.c"; then
	echo "Ошибка: нужен Xcode Command Line Tools (clang) для Mach-O загрузчика .app"
	exit 1
fi

if [ -f "$ROOT/assets/AppIcon.icns" ]; then
	cp -f "$ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
else
	echo "Предупреждение: нет assets/AppIcon.icns — иконка не вшита"
fi

echo "Готово. Перетащи WhisperClient.app в Программы."
echo "Нужны: Python 3 с pynput, requests, sounddevice, … (как в README)."
