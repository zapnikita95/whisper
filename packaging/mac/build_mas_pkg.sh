#!/bin/bash
# Mac App Store / TestFlight: .pkg из WhisperClient.app (не Developer ID DMG).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAC="$ROOT/packaging/mac"
APP="$MAC/WhisperClient.app"
OUTDIR="$ROOT/dist/release"
VERSION="$(tr -d ' \n\r' <"$ROOT/packaging/VERSION" 2>/dev/null || echo 1.0.0)"
BUILD="$(tr -d ' \n\r' <"$MAC/BUILD_NUMBER" 2>/dev/null || echo 1)"
PKG="$OUTDIR/WhisperClient-mas-${VERSION}-b${BUILD}.pkg"

BUNDLE_ID="$(tr -d ' \n\r' <"$MAC/BUNDLE_ID" 2>/dev/null || echo com.zapnikita95.WhisperClient)"
MAS_IDENTITY="${WHISPER_MAS_SIGN_IDENTITY:-}"
MAS_PROVISION="${WHISPER_MAS_PROVISION:-}"

if [ ! -d "$APP" ]; then
	echo "Сначала: bash packaging/build_mac_app.sh" >&2
	exit 1
fi

if [ -z "$MAS_IDENTITY" ]; then
	echo "Задай WHISPER_MAS_SIGN_IDENTITY='Apple Distribution: Nikita Zaporozhets (Y52BT2N4L8)'" >&2
	echo "Сертификат: Xcode → Settings → Accounts → Manage Certificates → Apple Distribution" >&2
	echo "См. packaging/mac/testflight/TESTFLIGHT.md" >&2
	exit 1
fi

# Автопоиск Mac App Store provisioning profile для bundle ID
if [ -z "$MAS_PROVISION" ]; then
	_XPROFILES="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
	if [ -d "$_XPROFILES" ]; then
		for _pf in "$_XPROFILES"/*.provisionprofile; do
			[ -f "$_pf" ] || continue
			if security cms -D -i "$_pf" 2>/dev/null | grep -q "$BUNDLE_ID"; then
				MAS_PROVISION="$_pf"
				echo "Найден provisioning profile: $_pf"
				break
			fi
		done
	fi
fi

mkdir -p "$OUTDIR"
ENT="$MAC/entitlements/WhisperClient.AppStore.plist"

echo "Подпись .app для Mac App Store (sandbox)…"
find "$APP" -name '*.cstemp*' -delete 2>/dev/null || true

# Встроить provisioning profile (обязательно для MAS)
if [ -n "$MAS_PROVISION" ] && [ -f "$MAS_PROVISION" ]; then
	cp -f "$MAS_PROVISION" "$APP/Contents/embedded.provisionprofile"
else
	echo "Предупреждение: Mac App Store provisioning profile не найден для $BUNDLE_ID" >&2
	echo "  developer.apple.com → Profiles → Mac App Store → $BUNDLE_ID → Download" >&2
fi

sign_args=(--force --deep --timestamp --options runtime --sign "$MAS_IDENTITY")
if [ -f "$ENT" ]; then
	sign_args+=(--entitlements "$ENT")
fi
codesign "${sign_args[@]}" "$APP"
codesign --verify --deep --strict "$APP"

echo "Сборка PKG → $PKG"
productbuild --component "$APP" /Applications --sign "$MAS_IDENTITY" "$PKG"
echo "Готово: $PKG"
echo "Загрузка: bash packaging/mac/upload_testflight.sh"
