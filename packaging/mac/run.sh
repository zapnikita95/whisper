#!/bin/bash
# Запуск из Finder даёт урезанный PATH — без Homebrew, из-за этого «краш» (не тот python / нет модулей).

# === Фикс для иконки в меню-баре и стабильности .app ===
export WHISPER_FROM_APP_BUNDLE=1
export PYTHONUNBUFFERED=1

# Лог до set -e: иначе любой провал $(cd …) убивает процесс с exit 1 (в логах launchd часто «256») — без окна и без подсказки.
RUN_LOG="${HOME}/Library/Logs/WhisperMacRun.log"
_run_log() {
	printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$RUN_LOG" 2>/dev/null || true
}
mkdir -p "${HOME}/Library/Logs" 2>/dev/null || true
_run_log "run.sh begin 0=$0 argv=$(printf '%q ' "$@")"

# Вызывается из Mach-O stub Contents/MacOS/WhisperClient; $0 = .../run.sh
set -euo pipefail

_ah_die_resources() {
	_run_log "$1"
	osascript <<'OSA' || true
display dialog "Whisper Client: не найдена папка Contents/Resources внутри .app. Скопируй приложение целиком (из DMG — перетащи Whisper Client в Программы), не только ярлык." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
}

_ah_die_macos() {
	_run_log "$1"
	osascript <<'OSA' || true
display dialog "Whisper Client: не удалось открыть папку Contents/MacOS (бандл повреждён или обрезанная копия)." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
}

_SCRIPT_DIR="$(dirname "$0")"
_SCRIPT_DIR="${_SCRIPT_DIR//$'\r'/}"
# С set -e провал cd внутри $() рвёт весь скрипт — поэтому || "" и явная проверка.
MACOS_DIR="$(cd "$_SCRIPT_DIR" 2>/dev/null && pwd)" || MACOS_DIR=""
MACOS_DIR="${MACOS_DIR//$'\r'/}"
[ -n "$MACOS_DIR" ] || _ah_die_macos "FAIL cd MacOS from _SCRIPT_DIR=$_SCRIPT_DIR"

R="$(cd "$MACOS_DIR/../Resources" 2>/dev/null && pwd)" || R=""
R="${R//$'\r'/}"
[ -n "$R" ] || _ah_die_resources "FAIL cd Resources MACOS_DIR=$MACOS_DIR"
[ -f "$R/whisper-client-mac.py" ] || _ah_die_resources "FAIL missing $R/whisper-client-mac.py"

# DMG vs локальная сборка (почему «из packaging/mac работает, из /Applications — нет»):
# macOS Privacy (TCC) привязан к *пути к .app* и к подписи бинарника. Копия из Desktop и копия
# из DMG в /Applications — для системы разные приложения: разрешения нужно выдать каждой копии.
# После установки из DMG: Системные настройки → Конфиденциальность → Микрофон / Ввод с клавиатуры /
# Универсальный доступ — добавь именно WhisperClient из Программ (или сброс: packaging/mac/reset_whisper_client_privacy.command).
#
# GITHUB_TOKEN для проверки обновлений: положи файл .env в одно из мест (Python подхватит при старте):
#   "$R/.env"  (рядом с whisper-client-mac.py внутри .app), или
#   "$HOME/Library/Application Support/WhisperClient/.env"  (предпочтительно для DMG — не трогает бандл).
# Репо: WhisperClient.app в packaging/mac/ → от Contents/MacOS пять уровней вверх = корень (там .venv/bin/python3)
if [ -z "${WHISPER_PYTHON3:-}" ]; then
	_REPO_ROOT=""
	if _RR="$(cd "$MACOS_DIR/../../../../../." 2>/dev/null && pwd)"; then
		_REPO_ROOT="$_RR"
	fi
	if [ -n "$_REPO_ROOT" ] && [ -x "$_REPO_ROOT/.venv/bin/python3" ]; then
		export WHISPER_PYTHON3="$_REPO_ROOT/.venv/bin/python3"
	fi
fi
# Если .app скопирован в /Applications без репозитория — подставь явный путь к venv (или export WHISPER_PYTHON3 в run.sh).
if [ -z "${WHISPER_PYTHON3:-}" ]; then
	for _try in \
		"${HOME}/Desktop/whisper/.venv/bin/python3" \
		"${HOME}/whisper/.venv/bin/python3" \
		"${HOME}/Projects/whisper/.venv/bin/python3"; do
		if [ -x "$_try" ]; then
			export WHISPER_PYTHON3="$_try"
			break
		fi
	done
fi
# shellcheck source=/dev/null
[ -f "$MACOS_DIR/pick_python_for_whisper.sh" ] || _ah_die_resources "FAIL missing pick_python_for_whisper.sh in $MACOS_DIR"
source "$MACOS_DIR/pick_python_for_whisper.sh" || {
	_run_log "FAIL source pick_python_for_whisper.sh"
	osascript <<'OSA' || true
display dialog "Whisper Client: ошибка загрузки pick_python_for_whisper.sh (бандл повреждён)." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
}
export PYTHONUNBUFFERED=1
export WHISPER_MAC_RESOURCES="$R"
# До pick: иначе pick_python не знает, что это .app (порядок интерпретаторов = сначала Python.org + rumps).
export WHISPER_FROM_APP_BUNDLE=1
export WHISPER_MAC_APP_PICK_PYTHON=1

PY="$(pick_python_for_whisper)" || {
	_run_log "FAIL pick_python_for_whisper (нет python3 с зависимостями)"
	osascript <<'OSA' || true
display dialog "Не найден подходящий python3 (нужны requests, sounddevice, numpy, soundfile, pyperclip; для Python 3.13 ещё pynput ≥ 1.8.1). Установи Python с python.org или Homebrew и выполни в Терминале: python3 -m pip install -U requests sounddevice numpy soundfile 'pynput>=1.8.1' pyperclip rumps. Либо задай WHISPER_PYTHON3 в run.sh внутри .app." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
}
_run_log "picked PY=$PY"

# Иконка 🎤 в меню-баре (rumps / NSStatusItem): при запуске из Finder процесс должен быть
# из Python.app (GUI), а не «голый» …/bin/python3.X — иначе AppKit часто не показывает статус-айтем.
# Зависимости из venv — через PYTHONPATH. ВАЖНО: сначала stdlib фреймворка (lib/pythonX.Y), потом
# site-packages; иначе в venv часто лежит устаревший pip-пакет «typing» и PyObjC падает при импорте —
# из Finder это выглядит как «.app вообще не запускается».
if [ "${WHISPER_FROM_APP_BUNDLE:-}" = "1" ]; then
	_GUI_PY="$("$PY" -c "
import pathlib, sys
e = pathlib.Path(sys.executable).resolve()
cur = e.parent
while cur != cur.parent:
	cand = cur / 'Resources/Python.app/Contents/MacOS/Python'
	if cand.is_file():
		print(cand)
		break
	cur = cur.parent
" 2>/dev/null || true)"
	_SITE="$("$PY" -c "import site; print(site.getsitepackages()[0])" 2>/dev/null || true)"
	_VER_MM="$("$PY" -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>/dev/null || true)"
	if [ -n "${_GUI_PY:-}" ] && [ -x "$_GUI_PY" ] && [ -n "${_SITE:-}" ] && [ -d "$_SITE" ] && [ -n "${_VER_MM:-}" ]; then
		# Пять уровней вверх от …/MacOS/Python до …/Versions/3.x (lib/pythonM.m)
		_ROOT_VER="$_GUI_PY"
		for _i in 1 2 3 4 5; do _ROOT_VER="$(dirname "$_ROOT_VER")"; done
		_FW_LIB="$_ROOT_VER/lib/python${_VER_MM}"
		export WHISPER_MAC_GUI_PYTHONAPP=1
		PY="$_GUI_PY"
		if [ -d "$_FW_LIB" ]; then
			export PYTHONPATH="${_FW_LIB}:${_SITE}${PYTHONPATH:+:$PYTHONPATH}"
		else
			export PYTHONPATH="${_SITE}${PYTHONPATH:+:$PYTHONPATH}"
		fi
	fi
fi

# Реальный бинарник интерпретатора (не Python Launcher / не оболочка .app).
export PYTHONEXECUTABLE="$PY"
export PYTHONDONTWRITEBYTECODE=1

if URL="$("$PY" "$R/pick_server_url.py" 2>/dev/null)" && [ -n "$URL" ]; then
	:
elif [ -n "${WHISPER_MAC_SERVER_URL:-}${WHISPER_SERVER_URL:-}" ]; then
	URL="${WHISPER_MAC_SERVER_URL:-${WHISPER_SERVER_URL:-}}"
	URL="${URL%/}"
else
	H="${WHISPER_MAC_SERVER_HOST:-100.115.68.2}"
	URL=""
	for port in ${WHISPER_MAC_SERVER_FALLBACK_PORTS:-8001 8000 8002 8003 8004 8005 8006 8007 8008 8009 8010 8011 8012 8013 8014 8015 8016 8017 8018 8019 8020}; do
		if "$PY" -c "
import json, sys, urllib.error, urllib.request
h, port = sys.argv[1], int(sys.argv[2])
try:
    r = urllib.request.urlopen(f'http://{h}:{port}/', timeout=2.5)
    d = json.loads(r.read().decode())
    raise SystemExit(0 if d.get('status') == 'ok' and 'model' in d else 1)
except Exception:
    raise SystemExit(1)
" "$H" "$port" 2>/dev/null; then
			URL="http://${H}:${port}"
			break
		fi
	done
	if [ -z "$URL" ]; then
		URL="http://${H}:${WHISPER_MAC_SERVER_PORT:-8000}"
	fi
fi

# Явный хоткей для .app: перебивает случайный WHISPER_MAC_HOTKEY из окружения.
export WHISPER_MAC_HOTKEY="shift+ctrl+alt"

# Эталон голоса уже есть — включаем проверку без флагов (отключить: WHISPER_MAC_NO_SPEAKER_VERIFY=1 в run.sh).
if [ -f "${HOME}/.whisper/speaker_embedding.npy" ] && [ "${WHISPER_MAC_NO_SPEAKER_VERIFY:-}" != "1" ]; then
	export WHISPER_SPEAKER_VERIFY=1
fi

# Finder передаёт -psn_0_… — не пробрасываем в Python (argparse).
CMD=( "$PY" "$R/whisper-client-mac.py" --server "$URL" --no-hotkey-prompt )
for a in "$@"; do
	case "$a" in
		-psn_*) ;;
		-NS*) ;; # иногда добавляет Cocoa / AppKit
		-Apple*) ;;
		*) CMD+=("$a") ;;
	esac
done
export WHISPER_NOTIFY_TOOL="$MACOS_DIR/whisper_notify"
# Нативный CGEventTap daemon (нет SIGTRAP / зависаний pynput на macOS 15+).
export WHISPER_HOTKEY_DAEMON="$MACOS_DIR/whisper_hotkey_daemon"
# Только whisper_notify + logger, без osascript: WHISPER_MAC_NO_OSASCRIPT_NOTIFY=1
# Авто-kick хоткея каждые N с простоя (не рекомендуется): WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC=300
_run_log "exec python PY=$PY URL=$URL argv=$(printf '%q ' "$@")"
set +e
"${CMD[@]}"
_ec=$?
set -e
_run_log "exit=$_ec"
exit "$_ec"
