#!/bin/bash
# Mac App Store / TestFlight: .pkg из WhisperClient.app (не Developer ID DMG).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAC="$ROOT/packaging/mac"
APP="$MAC/WhisperClient.app"
OUTDIR="$ROOT/dist/release"
VERSION="$(tr -d ' \n\r' <"$ROOT/packaging/VERSION" 2>/dev/null || echo 1.0.0)"
PKG="$OUTDIR/WhisperClient-mas-${VERSION}.pkg"

BUNDLE_ID="$(tr -d ' \n\r' <"$MAC/BUNDLE_ID" 2>/dev/null || echo com.zapnikita95.WhisperClient)"
MAS_IDENTITY="${WHISPER_MAS_SIGN_IDENTITY:-}"
MAS_PROVISION="${WHISPER_MAS_PROVISION:-}"

if [ ! -d "$APP" ]; then
	echo "Сначала: bash packaging/build_mac_app.sh" >&2
	exit 1
fi

if [ -z "$MAS_IDENTITY" ]; then
	echo "Задай WHISPER_MAS_SIGN_IDENTITY='Apple Distribution: … (Y52BT2N4L8)'" >&2
	echo "См. packaging/mac/testflight/TESTFLIGHT.md" >&2
	exit 1
fi

mkdir -p "$OUTDIR"
ENT="$MAC/entitlements/WhisperClient.AppStore.plist"

echo "Подпись .app для Mac App Store (sandbox)…"
find "$APP" -name '*.cstemp*' -delete 2>/dev/null || true

sign_args=(--force --deep --timestamp --options runtime --sign "$MAS_IDENTITY")
if [ -f "$ENT" ]; then
	sign_args+=(--entitlements "$ENT")
fi
if [ -n "$MAS_PROVISION" ] && [ -f "$MAS_PROVISION" ]; then
	sign_args+=(--entitlements "$MAS_PROVISION")
fi
codesign "${sign_args[@]}" "$APP"

echo "Сборка PKG → $PKG"
productbuild --component "$APP" /Applications --sign "$MAS_IDENTITY" "$PKG"
echo "Готово: $PKG"
echo "Загрузи в Transporter → App Store Connect → TestFlight (macOS)."
