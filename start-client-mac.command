#!/bin/bash
cd "$(dirname "$0")"

# Всегда этот хост; порт — из server_port.txt или первый ответящий из 8000–8010.
# Другой URL только если передать аргументом: ./start-client-mac.command 'http://другой:порт'

HOST="100.115.68.2"
CONNECT_TIMEOUT=3

# Только ответ whisper-server.py: GET / → JSON с status ok и полем model (не любой HTTP на порту).
is_whisper_port() {
    local p="$1"
    local body
    body=$(curl -sf --connect-timeout "$CONNECT_TIMEOUT" "http://${HOST}:${p}/") || return 1
    echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get('status')=='ok' and 'model' in d else 1)" 2>/dev/null
}

if [[ "${1:-}" =~ ^https?:// ]]; then
    SERVER_URL="$1"
    shift
else
    PORT=""
    if [ -f server_port.txt ]; then
        PORT=$(tr -d '[:space:]' < server_port.txt | tr -d '\r')
    fi

    if [ -n "$PORT" ] && is_whisper_port "$PORT"; then
        echo "✓ Сервер: http://${HOST}:${PORT} (из server_port.txt)"
    else
        if [ -n "$PORT" ] && [ -f server_port.txt ]; then
            echo "⚠ Порт из server_port.txt ($PORT) не похож на Whisper — ищу другой…"
        fi
        echo "Поиск Whisper API на ${HOST}, порты 8000–8010…"
        PORT=""
        for p in 8000 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010; do
            if is_whisper_port "$p"; then
                PORT=$p
                echo "✓ Найден Whisper на порту $PORT"
                break
            fi
        done
        if [ -z "$PORT" ]; then
            echo "✗ ОШИБКА: сервер не найден на 100.115.68.2:8000–8010"
            echo "Проверь Tailscale и что start-server.bat запущен на Windows."
            read -p "Нажми Enter для выхода..."
            exit 1
        fi
    fi
    SERVER_URL="http://${HOST}:${PORT}"
fi

if ! command -v python3 &> /dev/null; then
    echo "Ошибка: Python 3 не найден."
    read -p "Нажми Enter для выхода..."
    exit 1
fi

if [ ! -f "whisper-client-mac.py" ]; then
    echo "Ошибка: whisper-client-mac.py не найден."
    read -p "Нажми Enter для выхода..."
    exit 1
fi

if ! python3 -c "import requests, sounddevice, numpy, soundfile, pynput, pyperclip" 2>/dev/null; then
    echo "Установи зависимости:"
    echo "  pip3 install requests sounddevice numpy soundfile 'pynput>=1.8.1' pyperclip"
    echo ""
    read -p "Продолжить? (y/n) " -n 1 -r; echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

echo "Сервер: $SERVER_URL"
echo "При старте клиент спросит сочетание в терминале (Enter = ⌥+⌃)."
echo "  Без вопроса с ⌥+⌃: добавь  --no-hotkey-prompt"
echo "  Или сразу:  --hotkey 'ctrl+grave'  |  --bind-hotkey"
echo "Для выхода: Ctrl+C"
echo ""

python3 whisper-client-mac.py --server "$SERVER_URL" "$@"

read -p "Нажми Enter для выхода..."
