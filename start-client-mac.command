#!/bin/bash
cd "$(dirname "$0")"

TAILSCALE_IP="100.115.68.2"

# Читаем порт из server_port.txt (туда пишет start-server.bat)
if [ -f "server_port.txt" ]; then
    PORT=$(tr -d '[:space:]' < server_port.txt)
else
    PORT="8000"
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
