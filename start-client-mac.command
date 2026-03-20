#!/bin/bash
cd "$(dirname "$0")"

TAILSCALE_IP="100.115.68.2"

# Пробуем найти рабочий порт: сначала из файла, потом перебор 8000-8010
PORT=""
if [ -f "server_port.txt" ]; then
    PORT=$(tr -d '[:space:]' < server_port.txt)
fi

# Если файла нет или порт не работает - пробуем найти рабочий
if [ -z "$PORT" ] || ! curl -s --connect-timeout 2 "http://${TAILSCALE_IP}:${PORT}/" > /dev/null 2>&1; then
    echo "Поиск сервера на портах 8000-8010..."
    PORT=""
    for p in 8000 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010; do
        if curl -s --connect-timeout 2 "http://${TAILSCALE_IP}:${p}/" > /dev/null 2>&1; then
            PORT=$p
            echo "✓ Найден сервер на порту $PORT"
            break
        fi
    done
    if [ -z "$PORT" ]; then
        echo "✗ ОШИБКА: Сервер не найден на портах 8000-8010"
        echo "Убедись, что start-server.bat запущен на Windows"
        read -p "Нажми Enter для выхода..."
        exit 1
    fi
fi

SERVER_URL="http://${TAILSCALE_IP}:${PORT}"

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
    echo "  pip3 install requests sounddevice numpy soundfile pynput pyperclip"
    echo ""
    read -p "Продолжить? (y/n) " -n 1 -r; echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
fi

echo "Сервер: $SERVER_URL"
echo "Горячая клавиша: Cmd+Option (⌘⌥)"
echo "Для выхода: Ctrl+C"
echo ""

python3 whisper-client-mac.py --server "$SERVER_URL" "$@"

read -p "Нажми Enter для выхода..."
