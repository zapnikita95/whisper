#!/bin/bash
# Запуск из Finder даёт урезанный PATH — без Homebrew, из-за этого «краш» (не тот python / нет модулей).
set -euo pipefail
R="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PYTHONUNBUFFERED=1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

pick_python() {
	local c
	if [ -n "${WHISPER_PYTHON3:-}" ] && [ -x "${WHISPER_PYTHON3}" ]; then
		echo "${WHISPER_PYTHON3}"
		return 0
	fi
	c="$(command -v python3 2>/dev/null || true)"
	if [ -n "$c" ] && [ -x "$c" ]; then
		echo "$c"
		return 0
	fi
	for c in \
		/opt/homebrew/bin/python3 \
		/usr/local/bin/python3 \
		"$HOME/Library/Python/3.13/bin/python3" \
		"$HOME/Library/Python/3.12/bin/python3" \
		/usr/bin/python3
	do
		[ -x "$c" ] || continue
		echo "$c"
		return 0
	done
	return 1
}

PY="$(pick_python)" || {
	osascript <<'OSA'
display dialog "Не найден python3. Поставь Python 3 (brew или python.org) и зависимости из README." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
}

if ! "$PY" -c "import requests, sounddevice, numpy, soundfile, pynput, pyperclip" 2>/dev/null; then
	logger -t WhisperClient "missing pip deps for: $PY"
	osascript <<'OSA'
display dialog "Не хватает модулей (requests, pynput, sounddevice…). В Терминале выполни для ТОГО ЖЕ Python, что используешь для .command:

/opt/homebrew/bin/python3 -m pip install requests sounddevice numpy soundfile pynput pyperclip

Если python3 другой — замени путь (команда: which python3)." buttons {"OK"} default button 1 with title "Whisper Client"
OSA
	exit 1
fi

if URL="$("$PY" "$R/pick_server_url.py" 2>/dev/null)" && [ -n "$URL" ]; then
	:
else
	URL="http://100.115.68.2:8000"
fi

exec "$PY" "$R/whisper-client-mac.py" --server "$URL" --no-hotkey-prompt "$@"
