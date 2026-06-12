#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAC="$ROOT/packaging/mac"
APP="$MAC/WhisperClient.app"

# Автоподпись Developer ID: создай packaging/mac/whisper_codesign_local.env (см. .example) — тогда любой
# запуск этого скрипта (в т.ч. из Cursor) подписывает без ручного export.
# build_signed_app.sh выставляет WHISPER_CODESIGN_PREPARE_MODE=always — подпись даже без env-файла (GUI-пароль).
PREP_MODE="${WHISPER_CODESIGN_PREPARE_MODE:-auto}"
if [ "$PREP_MODE" = "always" ] || [ -f "$MAC/whisper_codesign_local.env" ]; then
	# shellcheck disable=SC1091
	source "$MAC/whisper_codesign_prepare.sh"
	echo "Подпись: WHISPER_MAC_CODESIGN_IDENTITY=${WHISPER_MAC_CODESIGN_IDENTITY}"
fi

# Иначе clang из Xcode 26 вшивает minos 26 → на macOS 15 и ниже «You can't use this version…»
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"
# Универсальный бинарь: коллеги на Intel; при ошибке x86_64 — собери на машине с полным SDK или убери -arch x86_64.
AH_ARCH_FLAGS="-arch arm64 -arch x86_64"
# Загрузчик .app: по умолчанию тот же universal, что и раньше. Только Apple Silicon: WHISPER_STUB_ARCH_FLAGS='-arch arm64'
WHISPER_STUB_ARCH_FLAGS="${WHISPER_STUB_ARCH_FLAGS:-$AH_ARCH_FLAGS}"

echo "Сборка $APP … (MACOSX_DEPLOYMENT_TARGET=$MACOSX_DEPLOYMENT_TARGET)"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -f "$MAC/Info.plist.template" "$APP/Contents/Info.plist"
cp -f "$ROOT/whisper-client-mac.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_groq.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_vocab.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_mac_defaults.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_mac_tk_dialogs.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_mac_vocab_ui.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_mac_cocoa_dialogs.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_mac_server_probe.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_version.py" "$APP/Contents/Resources/"
cp -f "$ROOT/whisper_update_check.py" "$APP/Contents/Resources/"
cp -f "$ROOT/speaker_verify.py" "$APP/Contents/Resources/"
cp -f "$ROOT/packaging/VERSION" "$APP/Contents/Resources/VERSION"
cp -f "$MAC/pick_server_url.py" "$APP/Contents/Resources/"
cp -f "$MAC/whisper_mic_capture.py" "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/whisper_mic_capture.py"
cp -f "$MAC/kill_whisper_client.command" "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/kill_whisper_client.command"
cp -f "$MAC/reset_whisper_client_privacy.command" "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/reset_whisper_client_privacy.command"
cp -f "$MAC/run.sh" "$APP/Contents/MacOS/run.sh"
cp -f "$MAC/pick_python_for_whisper.sh" "$APP/Contents/MacOS/pick_python_for_whisper.sh"
chmod +x "$APP/Contents/MacOS/run.sh"

if ! xcrun clang -O2 -Wall -Wextra $WHISPER_STUB_ARCH_FLAGS -o "$APP/Contents/MacOS/WhisperClient" "$MAC/whisper_stub.c"; then
	echo "Ошибка: нужен Xcode Command Line Tools (clang) для Mach-O загрузчика .app"
	echo "Только arm64: export WHISPER_STUB_ARCH_FLAGS='-arch arm64'"
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

# Вшитый venv — .app из /Applications не зависит от репозитория и глобального pip.
VENV_DIR="$APP/Contents/Resources/venv"
BUILD_PY="${WHISPER_BUNDLE_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13}"
if [ "${WHISPER_SKIP_BUNDLE_VENV:-}" != "1" ]; then
	echo "Вшиваю Python venv в .app (зависимости Mac-клиента)…"
	if [ ! -x "$BUILD_PY" ]; then
		BUILD_PY="$(command -v python3.13 2>/dev/null || command -v python3 2>/dev/null || true)"
	fi
	if [ -z "$BUILD_PY" ] || [ ! -x "$BUILD_PY" ]; then
		echo "Ошибка: нужен python3.13 для сборки venv (WHISPER_BUNDLE_PYTHON=…)" >&2
		exit 1
	fi
	if [ "${WHISPER_REFRESH_BUNDLE_VENV:-}" = "1" ] || [ ! -x "$VENV_DIR/bin/python3" ]; then
		rm -rf "$VENV_DIR"
		"$BUILD_PY" -m venv "$VENV_DIR"
		"$VENV_DIR/bin/python3" -m pip install -U pip wheel
		"$VENV_DIR/bin/python3" -m pip install -r "$ROOT/packaging/requirements-mac-client.txt"
		"$VENV_DIR/bin/python3" -m pip uninstall -y typing >/dev/null 2>&1 || true
	fi
	"$VENV_DIR/bin/python3" -c "import rumps, pynput, requests, sounddevice, numpy, soundfile, pyperclip; from importlib.metadata import version as v; assert tuple(int(x) for x in v('pynput').split('.')[:3]) >= (1,8,0)"
	echo "venv OK: $VENV_DIR/bin/python3"
fi

if [ -f "$ROOT/assets/AppIcon.icns" ]; then
	cp -f "$ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
else
	echo "Предупреждение: нет assets/AppIcon.icns — иконка не вшита"
fi

# Подпись:
# - По умолчанию ad-hoc (sign -) — без Apple Developer.
# - Своя подпись: export WHISPER_MAC_CODESIGN_IDENTITY="Apple Development: …" или "Developer ID Application: …"
#   см. packaging/mac/APPLE_SIGNING.md и security find-identity -v -p codesigning
# Прерванный codesign оставляет *.cstemp — без этого следующая подпись падает с «invalid … format».
find "$APP" -name '*.cstemp*' -delete 2>/dev/null || true

if [ -n "${WHISPER_MAC_CODESIGN_IDENTITY:-}" ]; then
	echo "Подпись codesign: ${WHISPER_MAC_CODESIGN_IDENTITY}"
	if codesign --force --deep --timestamp --options runtime \
		--sign "${WHISPER_MAC_CODESIGN_IDENTITY}" "$APP"; then
		:
	else
		echo "Предупреждение: подпись с --options runtime не удалась — пробую без hardened runtime."
		codesign --force --deep --timestamp --sign "${WHISPER_MAC_CODESIGN_IDENTITY}" "$APP"
	fi
else
	codesign --force --deep --sign - "$APP" 2>/dev/null || true
fi

# Finder часто показывает дату «Изменён» по корню .app; без touch внутренние правки не видны как «свежее».
touch "$APP"

echo "Готово. Перетащи WhisperClient.app в Программы."
echo "Нужны: Python 3 с pynput, requests, sounddevice, … (как в README)."
echo ""
echo "ВАЖНО (macOS Privacy): без WHISPER_MAC_CODESIGN_IDENTITY ad-hoc подпись каждый раз другая — старые разрешения"
echo "микрофона / мониторинга ввода могут не подходить (в Console: Failed to match … kTCCServiceListenEvent / Microphone)."
echo "Один раз запусти:  packaging/mac/reset_whisper_client_privacy.command"
echo "или в Терминале:"
echo "  tccutil reset Microphone local.whisper.client"
echo "  tccutil reset ListenEvent local.whisper.client"
echo "Потом снова открой .app и включи переключатели в Системных настройках."
