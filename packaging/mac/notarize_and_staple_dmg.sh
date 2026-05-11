#!/usr/bin/env bash
# Отправить DMG на нотаризацию и выполнить stapler (профиль из связки после notary_store_credentials.sh).
#
# Использование из корня репо:
#   bash packaging/mac/notarize_and_staple_dmg.sh
#   bash packaging/mac/notarize_and_staple_dmg.sh dist/release/WhisperClient-1.2.18.dmg
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV="$ROOT/packaging/mac/whisper_notary_local.env"
if [ -f "$ENV" ]; then
	set -a
	# shellcheck disable=SC1091
	source "$ENV"
	set +a
fi
PROFILE="${WHISPER_NOTARY_PROFILE:-whisper-notary}"

DMG="${1:-}"
if [ -z "$DMG" ]; then
	DMG="$(ls -t "$ROOT/dist/release"/WhisperClient-*.dmg 2>/dev/null | head -1 || true)"
fi
if [ -z "$DMG" ] || [ ! -f "$DMG" ]; then
	echo "Не найден DMG. Сначала: bash packaging/mac/release_mac_signed.sh"
	exit 1
fi

echo "Нотаризация: $DMG (профиль $PROFILE)"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
echo "Готово. Раздавай этот файл: $DMG"
