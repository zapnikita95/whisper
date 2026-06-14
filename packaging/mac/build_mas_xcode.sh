#!/bin/bash
# Mac App Store .pkg — venv в Frameworks/, единая подпись через exportArchive (без ad-hoc pre-sign).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAC="$ROOT/packaging/mac"
APP="$MAC/WhisperClient.app"
OUTDIR="$ROOT/dist/release"
ARCHIVE="$OUTDIR/WhisperClient.xcarchive"
EXPORT="$OUTDIR/mas-export"
VERSION="$(tr -d ' \n\r' <"$ROOT/packaging/VERSION" 2>/dev/null || echo 1.0.0)"
BUILD="$(tr -d ' \n\r' <"$MAC/BUILD_NUMBER" 2>/dev/null || echo 1)"
BUNDLE_ID="$(tr -d ' \n\r' <"$MAC/BUNDLE_ID" 2>/dev/null || echo com.zapnikita95.WhisperClient)"
ENT_MAIN="$MAC/entitlements/WhisperClient.AppStore.plist"
FINAL="$OUTDIR/WhisperClient-mas-${VERSION}-b${BUILD}.pkg"
DESKTOP="$HOME/Desktop/WhisperClient-mas.pkg"
VENV="$APP/Contents/Frameworks/venv"
RUNTIME_FW="$APP/Contents/Frameworks/WhisperRuntime.framework"
RUNTIME_ID="${BUNDLE_ID}.runtime"
MAS_PROVISION="${WHISPER_MAS_PROVISION:-$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles/1c99b4c5-7eec-4cef-951c-8ba97160803b.provisionprofile}"

ENV_FILE="$MAC/whisper_codesign_local.env"
if [ -f "$ENV_FILE" ]; then
	set -a
	# shellcheck disable=SC1091
	source "$ENV_FILE"
	set +a
fi
LOGIN_KC="${HOME}/Library/Keychains/login.keychain-db"
if [ -n "${WHISPER_LOGIN_KEYCHAIN_PASSWORD:-}" ] && [ -f "$LOGIN_KC" ]; then
	security unlock-keychain -p "$WHISPER_LOGIN_KEYCHAIN_PASSWORD" "$LOGIN_KC" 2>/dev/null || true
	security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$WHISPER_LOGIN_KEYCHAIN_PASSWORD" "$LOGIN_KC" 2>/dev/null || true
fi

_is_macho() { file "$1" 2>/dev/null | grep -q 'Mach-O'; }

_has_sandbox() {
	codesign -d --entitlements :- "$1" 2>/dev/null | grep -q 'com.apple.security.app-sandbox'
}

_get_ident() {
	codesign -dv "$1" 2>&1 | awk -F= '/^Identifier=/{print $2; exit}'
}

# Apple 90238: «valid on disk» + «does not satisfy designated Requirement»
_so_designated_ok() {
	local so="$1"
	local out
	out="$(codesign --verify --strict --verbose=2 "$so" 2>&1)" || {
		if echo "$out" | grep -q 'does not satisfy its designated Requirement'; then
			echo "$out" | tail -2 >&2
			return 1
		fi
	}
	return 0
}

echo "=== MAS build ${VERSION} (${BUILD}) ==="

echo "[1/5] .app без codesign, venv → Frameworks…"
rm -rf "$VENV" "$APP/Contents/Resources/venv"
WHISPER_MAS_BUILD=1 bash "$ROOT/packaging/build_mac_app.sh" 2>&1 | tail -3
[ -x "$VENV/bin/python3" ] || { echo "FAIL: нет $VENV/bin/python3" >&2; exit 1; }

echo "[2/5] чистка venv + сброс подписей…"
find "$APP" -type d -name '*.dSYM' -print0 2>/dev/null | while IFS= read -r -d '' _d; do rm -rf "$_d"; done
find "$APP" -type d -name '__pycache__' -print0 2>/dev/null | while IFS= read -r -d '' _d; do rm -rf "$_d"; done
rm -rf "$VENV/lib/python3.13/site-packages/PyObjCTest" 2>/dev/null || true
find "$VENV" -type f \( -name '*_tests.cpython*.so' -o -name '*_test.cpython*.so' \) -delete 2>/dev/null || true
# В Frameworks/bin только python — pip/activate ломают exportArchive (nested code).
find "$VENV/bin" -mindepth 1 -maxdepth 1 ! -name 'python' ! -name 'python3' ! -name 'python3.13' -exec rm -rf {} +
find "$VENV" -type f -name '.*' -delete 2>/dev/null || true
find "$VENV" -name '.gitignore' -delete 2>/dev/null || true

echo "[2b/5] venv → WhisperRuntime.framework (flat)…"
rm -rf "$RUNTIME_FW"
mkdir -p "$RUNTIME_FW/Resources"
mv "$VENV" "$RUNTIME_FW/Resources/venv"
VENV="$RUNTIME_FW/Resources/venv"
cp -f "$VENV/bin/python3.13" "$RUNTIME_FW/WhisperRuntime"
chmod +x "$RUNTIME_FW/WhisperRuntime"
cat >"$RUNTIME_FW/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key><string>en</string>
	<key>CFBundleExecutable</key><string>WhisperRuntime</string>
	<key>CFBundleIdentifier</key><string>${RUNTIME_ID}</string>
	<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
	<key>CFBundleName</key><string>WhisperRuntime</string>
	<key>CFBundlePackageType</key><string>FMWK</string>
	<key>CFBundleShortVersionString</key><string>${VERSION}</string>
	<key>CFBundleSupportedPlatforms</key>
	<array><string>MacOSX</string></array>
	<key>CFBundleVersion</key><string>${BUILD}</string>
	<key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST

echo "[2c/5] embed Python.framework (sandbox)…"
bash "$MAC/embed_python_mas.sh" "$APP" "$VENV"
install_name_tool -change "/Library/Frameworks/Python.framework/Versions/3.13/Python" \
	'@loader_path/../../../../Python.framework/Versions/3.13/Python' "$RUNTIME_FW/WhisperRuntime" 2>/dev/null || true

rm -rf "$APP/Contents/_CodeSignature"
while IFS= read -r -d '' _f; do
	_is_macho "$_f" && codesign --remove-signature "$_f" 2>/dev/null || true
done < <(find "$APP" -type f -print0)

echo "[3/5] provision profile + .sh в MacOS…"
if [ -f "$MAS_PROVISION" ]; then
	cp -f "$MAS_PROVISION" "$APP/Contents/embedded.provisionprofile"
else
	echo "FAIL: Mac App Store profile не найден: $MAS_PROVISION" >&2
	exit 1
fi
for _sh in run.sh pick_python_for_whisper.sh; do
	_f="$APP/Contents/MacOS/$_sh"
	[ -f "$_f" ] || continue
	chmod +x "$_f"
	codesign --force --sign - "$_f"
done

echo "[3c/5] inside-out sign (фикс 90238)…"
bash "$MAC/mas_sign_insidelout.sh" "$APP"

mkdir -p "$OUTDIR"
rm -rf "$ARCHIVE" "$EXPORT"
mkdir -p "$ARCHIVE/Products/Applications"
ditto "$APP" "$ARCHIVE/Products/Applications/WhisperClient.app"

cat >"$ARCHIVE/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>ApplicationProperties</key>
	<dict>
		<key>ApplicationPath</key>
		<string>Applications/WhisperClient.app</string>
		<key>Architectures</key>
		<array><string>arm64</string><string>x86_64</string></array>
		<key>CFBundleIdentifier</key>
		<string>${BUNDLE_ID}</string>
		<key>CFBundleShortVersionString</key>
		<string>${VERSION}</string>
		<key>CFBundleVersion</key>
		<string>${BUILD}</string>
		<key>Team</key>
		<string>Y52BT2N4L8</string>
	</dict>
	<key>ArchiveVersion</key>
	<integer>2</integer>
	<key>CreationDate</key>
	<date>$(date -u +"%Y-%m-%dT%H:%M:%SZ")</date>
	<key>Name</key>
	<string>WhisperClient</string>
	<key>SchemeName</key>
	<string>WhisperClient</string>
</dict>
</plist>
PLIST

echo "[4/5] exportArchive…"
xcodebuild -exportArchive \
	-archivePath "$ARCHIVE" \
	-exportPath "$EXPORT" \
	-exportOptionsPlist "$MAC/ExportOptions-MAS.plist" \
	-allowProvisioningUpdates

PKG=""
for f in "$EXPORT"/*.pkg "$EXPORT"/*/*.pkg; do
	[ -f "$f" ] && PKG="$f" && break
done
[ -n "$PKG" ] || { echo "нет .pkg после export" >&2; exit 1; }

cp -f "$PKG" "$FINAL"
rm -f "$HOME/Desktop/WhisperClient-mas-b"*.pkg 2>/dev/null || true
cp -f "$FINAL" "$DESKTOP"

echo "[5/5] проверка (90238 + sandbox)…"
TMPPKG="/tmp/whisper_mas_v_$$"
rm -rf "$TMPPKG"
pkgutil --expand-full "$FINAL" "$TMPPKG"
_PAYLOAD=$(find "$TMPPKG" -path '*/Payload/WhisperClient.app' -type d | head -1)
FAIL=0

_wc_id="$(_get_ident "$_PAYLOAD/Contents/MacOS/WhisperClient")"
if [ "$_wc_id" = "$BUNDLE_ID" ]; then
	echo "  ✓ WhisperClient identifier=$BUNDLE_ID"
else
	echo "  ✗ WhisperClient identifier=$_wc_id want $BUNDLE_ID" >&2; FAIL=1
fi

for _b in WhisperClient whisper_hotkey_daemon whisper_notify; do
	if _has_sandbox "$_PAYLOAD/Contents/MacOS/$_b"; then
		echo "  ✓ sandbox $_b"
	else
		echo "  ✗ sandbox $_b" >&2; FAIL=1
	fi
done

for _py in python3.13 python3 python; do
	_pf="$_PAYLOAD/Contents/Frameworks/WhisperRuntime.framework/Resources/venv/bin/$_py"
	if [ -f "$_pf" ] && _is_macho "$_pf"; then
		if _has_sandbox "$_pf"; then
			echo "  ✓ sandbox venv/$_py"
		else
			echo "  ✗ sandbox venv/$_py" >&2; FAIL=1
		fi
	fi
	_pfw="$_PAYLOAD/Contents/Frameworks/Python.framework/Versions/3.13/bin/$_py"
	if [ -f "$_pfw" ] && _is_macho "$_pfw"; then
		if _has_sandbox "$_pfw"; then
			echo "  ✓ sandbox Python.framework/bin/$_py"
		else
			echo "  ✗ sandbox Python.framework/bin/$_py" >&2; FAIL=1
		fi
	fi
done

_pyfw="$_PAYLOAD/Contents/Frameworks/Python.framework"
_pyfw_id="$(_get_ident "$_pyfw")"
if [ "$_pyfw_id" = "org.python.python" ]; then
	echo "  ✓ Python.framework identifier=org.python.python"
else
	echo "  ✗ Python.framework identifier=$_pyfw_id want org.python.python" >&2; FAIL=1
fi

if codesign --verify --deep --strict "$_PAYLOAD" 2>/dev/null; then
	echo "  ✓ codesign --verify --deep --strict"
else
	echo "  ✗ deep verify failed:" >&2
	codesign --verify --deep --strict "$_PAYLOAD" 2>&1 | head -6 >&2
	FAIL=1
fi

for _so in \
	"$_PAYLOAD/Contents/Frameworks/WhisperRuntime.framework/Resources/venv/lib/python3.13/site-packages/numpy/_core/_multiarray_umath.cpython-313-darwin.so" \
	"$_PAYLOAD/Contents/Frameworks/WhisperRuntime.framework/Resources/venv/lib/python3.13/site-packages/Quartz/ImageKit/_imagekit.cpython-313-darwin.so" \
	"$_PAYLOAD/Contents/Frameworks/WhisperRuntime.framework/Resources/venv/lib/python3.13/site-packages/AppKit/_AppKit.cpython-313-darwin.so"; do
	if [ -f "$_so" ]; then
		_bn=$(basename "$_so")
		if _so_designated_ok "$_so"; then
			echo "  ✓ designated OK $_bn"
		else
			echo "  ✗ designated FAIL $_bn" >&2; FAIL=1
		fi
	fi
done

rm -rf "$TMPPKG"
[ "$FAIL" -eq 0 ] || exit 1

echo ""
echo "ГОТОВО:"
echo "  $DESKTOP"
echo "  build ${VERSION} (${BUILD})"
ls -la "$DESKTOP"
