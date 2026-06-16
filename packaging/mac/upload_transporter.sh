#!/bin/bash
# Сборка MAS .pkg (нативный клиент, без Python) + загрузка в App Store Connect.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAC="$ROOT/packaging/mac"
OUTDIR="$ROOT/dist/release"
VERSION="$(tr -d ' \n\r' <"$ROOT/packaging/VERSION" 2>/dev/null || echo 1.0.0)"
BUILD="$(tr -d ' \n\r' <"$MAC/BUILD_NUMBER" 2>/dev/null || echo 1)"
PKG="${WHISPER_MAS_PKG:-$OUTDIR/WhisperClient-mas-${VERSION}-b${BUILD}.pkg}"
DESKTOP="$HOME/Desktop/WhisperClient-MAS-NO-PYTHON.pkg"
DESKTOP_ALIAS="$HOME/Desktop/WhisperClient-mas.pkg"
PKG="${WHISPER_MAS_PKG:-$DESKTOP}"
[ -f "$PKG" ] || PKG="$DESKTOP_ALIAS"
[ -f "$PKG" ] || PKG="$OUTDIR/WhisperClient-mas-${VERSION}-b${BUILD}.pkg"

if [ ! -f "$PKG" ]; then
	echo "Собираю native MAS pkg…" >&2
	bash "$MAC/build_mas_native.sh"
	PKG="$DESKTOP"
fi

chmod +x "$MAC/verify_mas_pkg.sh"
bash "$MAC/verify_mas_pkg.sh" "$PKG" || exit 1

ENV="$ROOT/packaging/mac/whisper_notary_local.env"
if [ -f "$ENV" ]; then
	# shellcheck source=/dev/null
	source "$ENV"
fi

APPLE_ID="${WHISPER_NOTARY_APPLE_ID:-}"
APP_PASSWORD="${WHISPER_NOTARY_APP_PASSWORD:-}"

if [ ! -f "$PKG" ]; then
	echo "PKG не найден: $PKG" >&2
	exit 1
fi

if [ -z "$APPLE_ID" ] || [ -z "$APP_PASSWORD" ]; then
	echo "Нужны WHISPER_NOTARY_APPLE_ID и WHISPER_NOTARY_APP_PASSWORD в whisper_notary_local.env" >&2
	exit 1
fi

ITMS="/Applications/Xcode.app/Contents/Developer/usr/bin/iTMSTransporter"
if [ ! -x "$ITMS" ]; then
	ITMS="$(xcrun --find iTMSTransporter 2>/dev/null || true)"
fi
[ -x "$ITMS" ] || ITMS="/Applications/Transporter.app/Contents/itms/bin/iTMSTransporter"

echo "Upload via Transporter: $PKG"
echo "Apple ID: $APPLE_ID"

"$ITMS" -m upload -assetFile "$PKG" -u "$APPLE_ID" -p "$APP_PASSWORD" -itc_provider "${WHISPER_NOTARY_TEAM_ID:-Y52BT2N4L8}" -v informational

# Fallback: altool (надёжнее для macOS .pkg)
if [ $? -ne 0 ] && xcrun altool --help >/dev/null 2>&1; then
	echo "Transporter failed, пробую altool…" >&2
	xcrun altool --upload-app -f "$PKG" -t macos -u "$APPLE_ID" -p "$APP_PASSWORD" --apple-id 6779807304
fi

echo ""
echo "Загружено. App Store Connect → TestFlight → macOS → билд ${VERSION} (${BUILD})."
