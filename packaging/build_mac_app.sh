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
cp -f "$MAC/pick_python_for_whisper.sh" "$APP/Contents/MacOS/pick_python_for_whisper.sh"
chmod +x "$APP/Contents/MacOS/run.sh"

if ! xcrun clang -O2 -Wall -Wextra -o "$APP/Contents/MacOS/WhisperClient" "$MAC/whisper_stub.c"; then
	echo "Ошибка: нужен Xcode Command Line Tools (clang) для Mach-O загрузчика .app"
	exit 1
fi

if xcrun clang -O2 -Wall -Wextra -framework Cocoa -o "$APP/Contents/MacOS/whisper_notify" "$MAC/whisper_notify.m" 2>/dev/null; then
	:
else
	echo "Предупреждение: не собран whisper_notify — уведомления останутся через osascript (часто «Python»)."
fi

if [ -f "$ROOT/assets/AppIcon.icns" ]; then
	cp -f "$ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
else
	echo "Предупреждение: нет assets/AppIcon.icns — иконка не вшита"
fi

# Локальная подпись — меньше сюрпризов у Gatekeeper при запуске из произвольной папки.
codesign --force --deep --sign - "$APP" 2>/dev/null || true

echo "Готово. Перетащи WhisperClient.app в Программы."
echo "Нужны: Python 3 с pynput, requests, sounddevice, … (как в README)."
