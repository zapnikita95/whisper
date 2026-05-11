#!/usr/bin/env bash
# GitHub Actions: опциональный импорт Developer ID (.p12 из секретов) → сборка → DMG → опционально notary.
# Секреты задаются только в GitHub → Settings → Secrets and variables → Actions.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

DEFAULT_IDENTITY='Developer ID Application: Nikita Zaporozhets (Y52BT2N4L8)'

if [ -n "${MACOS_CERTIFICATE_BASE64:-}" ] && [ -n "${MACOS_CERTIFICATE_PASSWORD:-}" ]; then
	RUNNER_TMP="${RUNNER_TEMP:-/tmp}"
	KEYCHAIN_PATH="$RUNNER_TMP/app-signing.keychain-db"
	KEYCHAIN_PASSWORD="${MACOS_KEYCHAIN_PASSWORD:-$(openssl rand -base64 24)}"
	P12_PATH="$RUNNER_TMP/developer_id.p12"

	echo "$MACOS_CERTIFICATE_BASE64" | base64 --decode >"$P12_PATH"

	security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
	security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
	security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
	security import "$P12_PATH" -k "$KEYCHAIN_PATH" -P "$MACOS_CERTIFICATE_PASSWORD" -f pkcs12 -T /usr/bin/codesign -A
	security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH" || true
	security list-keychain -d user -s "$KEYCHAIN_PATH"
	security default-keychain -s "$KEYCHAIN_PATH"
	security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"

	export WHISPER_MAC_CODESIGN_IDENTITY="${WHISPER_MAC_CODESIGN_IDENTITY:-$DEFAULT_IDENTITY}"
	echo "CI: импортирован .p12, подпись: ${WHISPER_MAC_CODESIGN_IDENTITY}"
	rm -f "$P12_PATH"
else
	echo "::notice title=macOS CI::Без MACOS_CERTIFICATE_BASE64 — ad-hoc подпись. Для Developer ID добавь секреты (см. packaging/mac/APPLE_SIGNING.md)."
fi

bash packaging/build_mac_app.sh

VERSION="${VERSION:-$(tr -d '\r\n' < packaging/VERSION)}"
export WHISPER_DMG_SKIP_APP_BUILD=1
brew install create-dmg 2>/dev/null || true
bash packaging/mac/make_dmg.sh "$VERSION"

if [ -n "${APPLE_NOTARY_APP_SPECIFIC_PASSWORD:-}" ] && [ -n "${NOTARY_APPLE_ID:-}" ]; then
	DMG="$(ls -t "$ROOT/dist/release"/WhisperClient-*.dmg 2>/dev/null | head -1 || true)"
	if [ -n "${DMG:-}" ] && [ -f "$DMG" ]; then
		TEAM="${NOTARY_TEAM_ID:-Y52BT2N4L8}"
		echo "CI: нотаризация $DMG"
		xcrun notarytool submit "$DMG" \
			--apple-id "$NOTARY_APPLE_ID" \
			--password "$APPLE_NOTARY_APP_SPECIFIC_PASSWORD" \
			--team-id "$TEAM" \
			--wait
		xcrun stapler staple "$DMG"
	fi
fi
