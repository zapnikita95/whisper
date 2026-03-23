#!/bin/bash
# Запуск из Finder даёт урезанный PATH — без Homebrew, из-за этого «краш» (не тот python / нет модулей).
# Вызывается из Mach-O stub Contents/MacOS/WhisperClient; $0 = .../run.sh
set -euo pipefail
R="$(cd "$(dirname "$0")/../Resources" && pwd)"
MACOS_DIR="$(cd "$(dirname "$0")" && pwd)"
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
source "$MACOS_DIR/pick_python_for_whisper.sh"
export PYTHONUNBUFFERED=1
export WHISPER_MAC_RESOURCES="$R"
# До pick: иначе pick_python не знает, что это .app (порядок интерпретаторов = сначала Python.org + rumps).
export WHISPER_FROM_APP_BUNDLE=1
export WHISPER_MAC_APP_PICK_PYTHON=1

PY="$(pick_python_for_whisper)" || {
	osascript <<'OSA'
display dialog "Не найден подходящий python3 (нужны requests, sounddevice, numpy, soundfile, pyperclip; для Python 3.13 ещё pynput ≥ 1.8.1). В Терминале: python3 -m pip install -U requests sounddevice numpy soundfile 'pynput>=1.8.1' pyperclip rumps. Либо WHISPER_PYTHON3 в run.sh." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
}

# Реальный бинарник интерпретатора (не Python Launcher / не оболочка .app).
export PYTHONEXECUTABLE="$PY"
export PYTHONDONTWRITEBYTECODE=1

if URL="$("$PY" "$R/pick_server_url.py" 2>/dev/null)" && [ -n "$URL" ]; then
	:
else
	URL="http://${WHISPER_MAC_SERVER_HOST:-100.115.68.2}:8000"
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
		*) CMD+=("$a") ;;
	esac
done
export WHISPER_NOTIFY_TOOL="$MACOS_DIR/whisper_notify"
# Только whisper_notify + logger, без osascript: WHISPER_MAC_NO_OSASCRIPT_NOTIFY=1
# Авто-kick хоткея каждые N с простоя (не рекомендуется): WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC=300
exec "${CMD[@]}"
