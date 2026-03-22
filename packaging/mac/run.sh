#!/bin/bash
# Запуск из Finder даёт урезанный PATH — без Homebrew, из-за этого «краш» (не тот python / нет модулей).
# Вызывается из Mach-O stub Contents/MacOS/WhisperClient; $0 = .../run.sh
set -euo pipefail
R="$(cd "$(dirname "$0")/../Resources" && pwd)"
MACOS_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$MACOS_DIR/pick_python_for_whisper.sh"
export PYTHONUNBUFFERED=1

PY="$(pick_python_for_whisper)" || {
	osascript <<'OSA'
display dialog "Не найден python3 с модулями (requests, pynput, sounddevice…). В Терминале для своего Python: python3 -m pip install requests sounddevice numpy soundfile 'pynput>=1.8.1' pyperclip. Либо задай WHISPER_PYTHON3 в run.sh." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
}

if URL="$("$PY" "$R/pick_server_url.py" 2>/dev/null)" && [ -n "$URL" ]; then
	:
else
	URL="http://${WHISPER_MAC_SERVER_HOST:-100.115.68.2}:8000"
fi

# Явный хоткей для .app: перебивает случайный WHISPER_MAC_HOTKEY из окружения.
export WHISPER_MAC_HOTKEY="shift+ctrl+grave"

# Finder передаёт -psn_0_… — не пробрасываем в Python (argparse).
CMD=( "$PY" "$R/whisper-client-mac.py" --server "$URL" --no-hotkey-prompt )
for a in "$@"; do
	case "$a" in
		-psn_*) ;;
		*) CMD+=("$a") ;;
	esac
done
export WHISPER_FROM_APP_BUNDLE=1
exec "${CMD[@]}"
