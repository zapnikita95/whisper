#!/bin/bash
# Запуск из Cursor/другой IDE без pseudo-TTY даёт: [forkpty: Device not configured].
# Тогда открываем настоящий Terminal.app (там есть /dev/tty). Обход: WHISPER_MAC_COMMAND_SKIP_TTY_REDIRECT=1
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
SELF="$HERE/$(basename "$0")"
cd "$HERE" || exit 1

# Локальный venv в корне репо (см. packaging/mac/setup_mac_venv.sh)
if [ -z "${WHISPER_PYTHON3:-}" ] && [ -x "$HERE/.venv/bin/python3" ]; then
	export WHISPER_PYTHON3="$HERE/.venv/bin/python3"
fi

# Нативный CGEventTap daemon (нет SIGTRAP / зависаний pynput на macOS 15+).
# Собираем один раз при первом запуске если бинарь ещё не существует.
_DAEMON_BIN="$HERE/packaging/mac/whisper_hotkey_daemon"
_DAEMON_SRC="$HERE/packaging/mac/whisper_hotkey_daemon.c"
if [ ! -x "$_DAEMON_BIN" ] && [ -f "$_DAEMON_SRC" ] && command -v clang >/dev/null 2>&1; then
	echo "Компилирую whisper_hotkey_daemon (CGEventTap, один раз)…"
	clang -O2 -framework ApplicationServices -framework Carbon \
		-o "$_DAEMON_BIN" "$_DAEMON_SRC" 2>/dev/null && \
		echo "✓ whisper_hotkey_daemon готов." || \
		echo "⚠ Не удалось скомпилировать whisper_hotkey_daemon (fallback на pynput)."
fi
if [ -x "$_DAEMON_BIN" ]; then
	export WHISPER_HOTKEY_DAEMON="$_DAEMON_BIN"
fi

if [ ! -t 0 ] && [ -z "${WHISPER_MAC_COMMAND_SKIP_TTY_REDIRECT:-}" ]; then
	echo "Нет интерактивного TTY (часто при «Run» из Cursor). Открываю Terminal.app…" >&2
	exec open -a Terminal "$SELF"
	exit 0
fi

# shellcheck source=/dev/null
source "$HERE/packaging/mac/pick_python_for_whisper.sh"

if ! PY="$(pick_python_for_whisper)"; then
	echo "Ошибка: нет python3 с модулями Mac-клиента."
	echo "  Один раз: bash packaging/mac/setup_mac_venv.sh"
	echo "  Или вручную: WHISPER_PYTHON3=/путь/к/python3 с requests, sounddevice, numpy, soundfile, 'pynput>=1.8.1', pyperclip, rumps"
	[ -t 0 ] && read -p "Нажми Enter для выхода..."
	exit 1
fi

if [ ! -f "whisper-client-mac.py" ]; then
	echo "Ошибка: whisper-client-mac.py не найден (запускай из корня репозитория whisper)."
	[ -t 0 ] && read -p "Нажми Enter для выхода..."
	exit 1
fi

# IP Windows в Tailscale: WHISPER_MAC_SERVER_HOST (по умолчанию старый пример из репо).
export WHISPER_MAC_SERVER_HOST="${WHISPER_MAC_SERVER_HOST:-100.115.68.2}"
H="$WHISPER_MAC_SERVER_HOST"

# Явный URL: ./start-client-mac.command 'http://IP:ПОРТ'
if [[ "${1:-}" =~ ^https?:// ]]; then
	SERVER_URL="$1"
	shift
else
	SERVER_URL=""
	# Быстрая проверка server_port.txt (один curl)
	if [ -f server_port.txt ]; then
		HPORT=$(tr -d '[:space:]' < server_port.txt | tr -d '\r')
		if [ -n "$HPORT" ]; then
			if body=$(curl -sf --connect-timeout 2 "http://${H}:${HPORT}/") && echo "$body" | "$PY" -c "import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get('status')=='ok' and 'model' in d else 1)" 2>/dev/null; then
				SERVER_URL="http://${H}:${HPORT}"
				echo "✓ Сервер: $SERVER_URL (из server_port.txt + проверка /)"
			fi
		fi
	fi
	if [ -z "$SERVER_URL" ]; then
		echo "Поиск Whisper API на $H:8000–8010 (параллельно, ~2 c)…"
		if DETECTED="$("$PY" "$HERE/packaging/mac/pick_server_url.py" 2>/dev/null)" && [ -n "$DETECTED" ]; then
			SERVER_URL="$DETECTED"
			echo "✓ Сервер: $SERVER_URL"
		else
			SERVER_URL="http://${H}:8000"
			echo "⚠ API не ответил — подставляю $SERVER_URL (клиент всё равно запустится)."
			echo "  Укажи IP: export WHISPER_MAC_SERVER_HOST=твой_tailscale_ip"
			echo "  Или URL: ./start-client-mac.command 'http://IP:ПОРТ'"
		fi
	fi
fi

echo "Сервер: $SERVER_URL"
echo "При старте клиент спросит сочетание в терминале (Enter = ⌃+⇧+⌥ — без \` в тексте и без спама терминалом Cursor)."
echo "  Без вопроса:  --no-hotkey-prompt   (или export WHISPER_MAC_HOTKEY='shift+ctrl+alt')"
echo "  Или сразу:  --hotkey 'alt+ctrl'  |  --hotkey 'ctrl+grave'  |  --bind-hotkey"
echo "Для выхода: Ctrl+C"
echo ""

"$PY" whisper-client-mac.py --server "$SERVER_URL" "$@"
[ -t 0 ] && read -p "Нажми Enter для выхода..."
