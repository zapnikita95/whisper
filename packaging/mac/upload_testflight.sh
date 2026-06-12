#!/bin/bash
# Загрузка Mac App Store .pkg в App Store Connect / TestFlight.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUTDIR="$ROOT/dist/release"
VERSION="$(tr -d ' \n\r' <"$ROOT/packaging/VERSION" 2>/dev/null || echo 1.0.0)"
BUILD="$(tr -d ' \n\r' <"$ROOT/packaging/mac/BUILD_NUMBER" 2>/dev/null || echo 1)"
PKG="${WHISPER_MAS_PKG:-$OUTDIR/WhisperClient-mas-${VERSION}-b${BUILD}.pkg}"

ENV="$ROOT/packaging/mac/whisper_notary_local.env"
if [ -f "$ENV" ]; then
	# shellcheck source=/dev/null
	source "$ENV"
fi

APPLE_ID="${WHISPER_NOTARY_APPLE_ID:-}"
APP_PASSWORD="${WHISPER_NOTARY_APP_PASSWORD:-}"
PROFILE="${WHISPER_NOTARY_PROFILE:-whisper-notary}"

if [ ! -f "$PKG" ]; then
	echo "PKG не найден: $PKG" >&2
	echo "Сначала: bash packaging/mac/build_mas_pkg.sh" >&2
	exit 1
fi

echo "Upload → TestFlight: $PKG"

if xcrun altool --help >/dev/null 2>&1; then
	if [ -n "$APPLE_ID" ] && [ -n "$APP_PASSWORD" ]; then
		xcrun altool --upload-app -f "$PKG" -t macos -u "$APPLE_ID" -p "$APP_PASSWORD"
		echo "Загружено. App Store Connect → TestFlight → macOS → internal testing."
		exit 0
	fi
	if security find-generic-password -s "$PROFILE" >/dev/null 2>&1; then
		xcrun altool --upload-app -f "$PKG" -t macos -u "$APPLE_ID" -p "@keychain:$PROFILE"
		echo "Загружено через keychain profile $PROFILE."
		exit 0
	fi
fi

if command -v fastlane >/dev/null 2>&1; then
	export FASTLANE_APPLE_APPLICATION_SPECIFIC_PASSWORD="$APP_PASSWORD"
	fastlane deliver upload_metadata:false skip_screenshots:true skip_binary_upload:false \
		--pkg "$PKG" \
		--platform osx \
		--username "$APPLE_ID" \
		--app_identifier com.zapnikita95.WhisperClient \
		--skip_app_version_update true \
		--force 2>/dev/null || true
fi

echo "Не удалось загрузить автоматически." >&2
echo "1. Установи Transporter из App Store" >&2
echo "2. Перетащи $PKG в Transporter" >&2
echo "3. Или: xcrun altool --upload-app -f \"$PKG\" -t macos -u APPLE_ID -p APP_SPECIFIC_PASSWORD" >&2
exit 1
