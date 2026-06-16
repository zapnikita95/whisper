#!/bin/bash
# Inside-out подпись .app перед exportArchive (иначе MAS 90238 на venv .so).
set -euo pipefail
APP="${1:?usage: mas_sign_insidelout.sh WhisperClient.app}"
MAC="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC/../.." && pwd)"
BUNDLE_ID="$(tr -d ' \n\r' <"$MAC/BUNDLE_ID" 2>/dev/null || echo com.zapnikita95.WhisperClient)"
BUILD="$(tr -d ' \n\r' <"$MAC/BUILD_NUMBER" 2>/dev/null || echo 1)"
ENT_MAIN="$MAC/entitlements/WhisperClient.AppStore.plist"
ENT_HELPER="$MAC/entitlements/WhisperHelper.AppStore.plist"
RUNTIME_ID="${BUNDLE_ID}.runtime"
PYFW_ID="org.python.python"
FW="$APP/Contents/Frameworks/WhisperRuntime.framework"

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

_is_macho() { file "$1" 2>/dev/null | grep -q 'Mach-O'; }

IDENT="${WHISPER_MAS_SIGN_IDENTITY:-$(_pick_identity || true)}"
[ -n "$IDENT" ] || {
	echo "FAIL: нет Apple Development / Distribution в связке ключей." >&2
	echo "  Xcode → Settings → Accounts → Manage Certificates → + → Apple Development" >&2
	exit 1
}
echo "MAS inside-out sign: $IDENT"

_sign_nested_so() {
	local root="$1"
	[ -d "$root" ] || return 0
	find "$root" -type f \( -name '*.so' -o -name '*.dylib' \) -print0 2>/dev/null | \
		xargs -0 -P 8 -I {} codesign --force --sign "$IDENT" --options runtime "{}"
}

# .so/.dylib в WhisperRuntime (venv) и lib-dynload (stdlib) — до обёртки Python.framework.
_sign_nested_so "$FW"
_sign_nested_so "$APP/Contents/Frameworks/Python.framework/Versions/3.13/lib/python3.13/lib-dynload"

PYBIN="$APP/Contents/Frameworks/Python.framework/Versions/3.13/Python"
PYFW_BIN="$APP/Contents/Frameworks/Python.framework/Versions/3.13/bin"
PYAPP="$APP/Contents/Frameworks/Python.framework/Versions/3.13/Resources/Python.app"
PYAPP_EXE="$PYAPP/Contents/MacOS/Python"
[ -f "$PYBIN" ] && codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$PYFW_ID" --entitlements "$ENT_HELPER" "$PYBIN"
[ -f "$PYAPP_EXE" ] && codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$PYFW_ID" --entitlements "$ENT_HELPER" "$PYAPP_EXE"
for _py in python3.13 python3 python; do
	_f="$PYFW_BIN/$_py"
	[ -f "$_f" ] && _is_macho "$_f" && \
		codesign --force --sign "$IDENT" --options runtime --timestamp \
			--identifier "$PYFW_ID" --entitlements "$ENT_HELPER" "$_f"
done
[ -d "$PYAPP" ] && codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$PYFW_ID" --entitlements "$ENT_HELPER" "$PYAPP"
[ -d "$APP/Contents/Frameworks/Python.framework" ] && \
	codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$PYFW_ID" --entitlements "$ENT_HELPER" "$APP/Contents/Frameworks/Python.framework"

# whisper_python — Mach-O без sandbox (не в списке 409; наследует контейнер .app).
WP="$APP/Contents/MacOS/whisper_python"
[ -f "$WP" ] && _is_macho "$WP" && \
	codesign --force --sign "$IDENT" --options runtime --timestamp \
		--identifier "${BUNDLE_ID}.python" "$WP"

# venv/bin/* и WhisperRuntime — shell, не подписывать с sandbox (409: не Mach-O).
# Печать framework — sandbox на обёртку (Info.plist есть).
[ -d "$FW" ] && codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$RUNTIME_ID" --entitlements "$ENT_HELPER" "$FW"

for _b in whisper_hotkey_daemon whisper_notify; do
	[ -f "$APP/Contents/MacOS/$_b" ] && \
		codesign --force --sign "$IDENT" --options runtime --timestamp \
			--identifier "${BUNDLE_ID}.${_b}" --entitlements "$ENT_HELPER" "$APP/Contents/MacOS/$_b"
done

codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$BUNDLE_ID" --entitlements "$ENT_MAIN" "$APP/Contents/MacOS/WhisperClient"

for _sh in run.sh pick_python_for_whisper.sh; do
	_f="$APP/Contents/MacOS/$_sh"
	[ -f "$_f" ] && codesign --force --sign - "$_f" 2>/dev/null || true
done

codesign --force --sign "$IDENT" --options runtime --timestamp \
	--identifier "$BUNDLE_ID" --entitlements "$ENT_MAIN" "$APP"

echo "  ✓ inside-out sign OK (build $BUILD)"
