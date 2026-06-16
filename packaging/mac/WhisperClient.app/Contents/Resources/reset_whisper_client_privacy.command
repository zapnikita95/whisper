#!/bin/bash
# После смены подписи / bundle ID сброс TCC (микрофон, мониторинг ввода).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/BUNDLE_ID" ]; then
	BID="$(tr -d ' \n\r' <"$SCRIPT_DIR/BUNDLE_ID")"
elif [ -f "$SCRIPT_DIR/../Info.plist" ]; then
	BID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$SCRIPT_DIR/../Info.plist" 2>/dev/null || true)"
fi
BID="${BID:-com.zapnikita95.WhisperClient}"
echo "Bundle ID: $BID"
for svc in Microphone ListenEvent Accessibility AppleEvents; do
	if tccutil reset "$svc" "$BID" 2>/dev/null; then
		echo "  tccutil reset $svc $BID — OK"
	else
		echo "  tccutil reset $svc $BID — пропуск (нужен Full Disk Access для Terminal?)"
	fi
done
echo ""
echo "Теперь запусти WhisperClient.app заново и включи переключатели в «Конфиденциальность и безопасность»."
echo "Старые записи local.whisper.client и Python можно удалить из списков вручную."
