#!/bin/bash
# Завершает клиент Whisper для macOS. В «Принудительное завершение» (⌥⌘⎋) его нет — это LSUIElement/Accessory.
set -euo pipefail
cd "$(dirname "$0")" || exit 1
echo "Ищу процесс whisper-client-mac.py …"
if pgrep -fl "whisper-client-mac.py" >/dev/null 2>&1; then
	pgrep -fl "whisper-client-mac.py" || true
	pkill -f "whisper-client-mac.py" && echo "Готово: процесс завершён." || echo "Не удалось завершить (права?)."
else
	echo "Процесс не найден — клиент уже не запущен."
	echo "Подсказка: в Мониторинге системы включи «Все процессы» и ищи Python с whisper-client-mac в столбце команды."
fi
echo ""
read -r -p "Enter — закрыть окно " _
