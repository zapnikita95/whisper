#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAC="$ROOT/packaging/mac"
APP="$MAC/WhisperClient.app"

# Иначе clang из Xcode 26 вшивает minos 26 → на macOS 15 и ниже «You can't use this version…»
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"
# Универсальный бинарь: коллеги на Intel; при ошибке x86_64 — собери на машине с полным SDK или убери -arch x86_64.
AH_ARCH_FLAGS="-arch arm64 -arch x86_64"

echo "Сборка $APP … (MACOSX_DEPLOYMENT_TARGET=$MACOSX_DEPLOYMENT_TARGET)"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -f "$MAC/Info.plist.template" "$APP/Contents/Info.plist"
cp -f "$ROOT/whisper-client-mac.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_version.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_update_check.py" "$APP/Contents/Resources/"
cp -f "$ROOT/speaker_verify.py" "$APP/Contents/Resources/"
cp -f "$ROOT/packaging/VERSION" "$APP/Contents/Resources/VERSION"
cp -f "$MAC/pick_server_url.py" "$APP/Contents/Resources/"
cp -f "$MAC/kill_whisper_client.command" "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/kill_whisper_client.command"
cp -f "$MAC/reset_whisper_client_privacy.command" "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/reset_whisper_client_privacy.command"
cp -f "$MAC/run.sh" "$APP/Contents/MacOS/run.sh"
cp -f "$MAC/pick_python_for_whisper.sh" "$APP/Contents/MacOS/pick_python_for_whisper.sh"
chmod +x "$APP/Contents/MacOS/run.sh"

if ! xcrun clang -O2 -Wall -Wextra $AH_ARCH_FLAGS -o "$APP/Contents/MacOS/WhisperClient" "$MAC/whisper_stub.c"; then
	echo "Ошибка: нужен Xcode Command Line Tools (clang) для Mach-O загрузчика .app"
	echo "Если ругается на x86_64: export AH_ARCH_FLAGS='-arch arm64' и пересобери (только Apple Silicon)."
	exit 1
fi

if xcrun clang -O2 -Wall -Wextra $AH_ARCH_FLAGS -framework Cocoa -framework UserNotifications \
	-o "$APP/Contents/MacOS/whisper_notify" "$MAC/whisper_notify.m" 2>/dev/null; then
	:
else
	echo "Предупреждение: не собран whisper_notify — уведомления останутся через osascript (часто «Python»)."
fi

# Нативный CGEventTap daemon: нет TSM-крашей и зависаний pynput на macOS 15+.
if xcrun clang -O2 -Wall $AH_ARCH_FLAGS -framework ApplicationServices -framework Carbon \
       -o "$APP/Contents/MacOS/whisper_hotkey_daemon" "$MAC/whisper_hotkey_daemon.c" 2>/dev/null; then
	echo "Скомпилирован whisper_hotkey_daemon — нативный CGEventTap (нет SIGTRAP/зависаний)."
	# Копируем рядом с репо для dev-запуска через start-client-mac.command
	cp -f "$APP/Contents/MacOS/whisper_hotkey_daemon" "$MAC/whisper_hotkey_daemon"
else
	echo "Предупреждение: не собран whisper_hotkey_daemon — hotkey через pynput (fallback)."
fi

if [ -f "$ROOT/assets/AppIcon.icns" ]; then
	cp -f "$ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
else
	echo "Предупреждение: нет assets/AppIcon.icns — иконка не вшита"
fi

# Локальная подпись — меньше сюрпризов у Gatekeeper при запуске из произвольной папки.
codesign --force --deep --sign - "$APP" 2>/dev/null || true

# Finder часто показывает дату «Изменён» по корню .app; без touch внутренние правки не видны как «свежее».
touch "$APP"

echo "Готово. Перетащи WhisperClient.app в Программы."
echo "Нужны: Python 3 с pynput, requests, sounddevice, … (как в README)."
echo ""
echo "ВАЖНО (macOS Privacy): после каждой пересборки ad-hoc подпись меняется — старые разрешения"
echo "микрофона / мониторинга ввода могут не подходить (в Console: Failed to match … kTCCServiceListenEvent / Microphone)."
echo "Один раз запусти:  packaging/mac/reset_whisper_client_privacy.command"
echo "или в Терминале:"
echo "  tccutil reset Microphone local.whisper.client"
echo "  tccutil reset ListenEvent local.whisper.client"
echo "Потом снова открой .app и включи переключатели в Системных настройках."
