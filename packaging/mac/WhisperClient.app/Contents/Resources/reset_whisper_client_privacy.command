#!/bin/bash
# После packaging/build_mac_app.sh с ad-hoc codesign подпись .app меняется → TCC не совпадает со старыми
# разрешениями (в логах: Failed to match existing code requirement … kTCCServiceMicrophone).
# Запусти этот скрипт и снова выдай микрофон / мониторинг ввода для Whisper Client.
set -euo pipefail
cd "$(dirname "$0")" || exit 1
BID="local.whisper.client"
echo "Сброс разрешений для $BID …"
for svc in Microphone ListenEvent Accessibility AppleEvents; do
	if tccutil reset "$svc" "$BID" 2>/dev/null; then
		echo "  OK: $svc"
	else
		echo "  (пропуск или нет записей: $svc)"
	fi
done
echo ""
echo "Теперь запусти WhisperClient.app заново и включи переключатели в «Конфиденциальность и безопасность»."
read -r -p "Enter — закрыть " _
