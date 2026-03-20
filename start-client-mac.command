#!/bin/bash
# Скрипт для запуска Whisper клиента на Mac
# Использование: двойной клик в Finder или ./start-client-mac.command

# Переходим в папку со скриптом
cd "$(dirname "$0")"

# IP сервера (Tailscale)
SERVER_URL="http://100.115.68.2:8000"

# Проверяем наличие Python 3
if ! command -v python3 &> /dev/null; then
    echo "Ошибка: Python 3 не найден. Установи Python 3."
    read -p "Нажми Enter для выхода..."
    exit 1
fi

# Проверяем наличие скрипта клиента
if [ ! -f "whisper-client-mac.py" ]; then
    echo "Ошибка: файл whisper-client-mac.py не найден в текущей папке."
    read -p "Нажми Enter для выхода..."
    exit 1
fi

# Проверяем зависимости (простая проверка)
if ! python3 -c "import requests, sounddevice, numpy, soundfile, pynput, pyperclip" 2>/dev/null; then
    echo "ВНИМАНИЕ: некоторые зависимости не установлены."
    echo "Установи: pip3 install requests sounddevice numpy soundfile pynput pyperclip"
    echo ""
    read -p "Продолжить всё равно? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Запуск Whisper клиента..."
echo "Сервер: $SERVER_URL"
echo "Горячая клавиша: Cmd+Option (⌘⌥)"
echo "Для выхода: Ctrl+C"
echo ""

# Запускаем клиент
python3 whisper-client-mac.py --server "$SERVER_URL" "$@"

# Если скрипт завершился (не Ctrl+C), ждём нажатия Enter
if [ $? -eq 0 ] || [ $? -eq 130 ]; then
    echo ""
    read -p "Нажми Enter для выхода..."
fi
