#!/bin/bash
# Подпись MAS .app — один WhisperClient Mach-O, без Python/helpers.
set -euo pipefail
APP="${1:?usage: mas_sign_native.sh WhisperClient.app}"
MAC="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_ID="$(tr -d ' \n\r' <"$MAC/BUNDLE_ID" 2>/dev/null || echo com.zapnikita95.WhisperClient)"
BUILD="$(tr -d ' \n\r' <"$MAC/BUILD_NUMBER" 2>/dev/null || echo 1)"
ENT_MAIN="$MAC/entitlements/WhisperClient.AppStore.plist"

_pick_identity() {
	local line id
	for pat in 'Apple Development:' 'Apple Distribution:' '3rd Party Mac Developer Application:'; do
		line="$(security find-identity -v -p codesigning 2>/dev/null | grep "$pat" | head -1 || true)"
		[ -n "$line" ] || continue
		id="$(printf '%s\n' "$line" | sed -n 's/.*"\(.*\)"/\1/p')"
		[ -n "$id" ] && echo "$id" && return 0
	done
	return 1
}

IDENT="${WHISPER_MAS_SIGN_IDENTITY:-$(_pick_identity || true)}"
[ -n "$IDENT" ] || { echo "FAIL: нет Apple Development / Distribution." >&2; exit 1; }
echo "MAS sign (single binary): $IDENT"

codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$BUNDLE_ID" --entitlements "$ENT_MAIN" "$APP/Contents/MacOS/WhisperClient"

codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$BUNDLE_ID" --entitlements "$ENT_MAIN" "$APP"

echo "  ✓ MAS sign OK (build $BUILD)"
