#!/usr/bin/env bash
# Один вход: подписанный WhisperClient.app + DMG в dist/release (без лишних пересборок).
#
# Один раз настрой packaging/mac/whisper_codesign_local.env (см. whisper_codesign_local.env.example).
# Дальше из корня репозитория:
#   bash packaging/mac/release_mac_signed.sh
# Только .app без DMG:
#   WHISPER_MAC_SKIP_DMG=1 bash packaging/mac/release_mac_signed.sh
# Версия DMG (по умолчанию из packaging/VERSION):
#   bash packaging/mac/release_mac_signed.sh 1.2.3
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

bash packaging/mac/build_signed_app.sh

if [ "${WHISPER_MAC_SKIP_DMG:-}" = "1" ]; then
	echo "Готово: $ROOT/packaging/mac/WhisperClient.app (DMG пропущен, WHISPER_MAC_SKIP_DMG=1)"
	exit 0
fi

WHISPER_DMG_SKIP_APP_BUILD=1 bash packaging/mac/make_dmg.sh "$@"
echo ""
echo "Готово: packaging/mac/WhisperClient.app и DMG в dist/release/"
