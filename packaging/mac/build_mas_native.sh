#!/bin/bash
# Mac App Store / TestFlight — ОДИН нативный Mach-O, БЕЗ Python/Frameworks/helpers.
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
FINAL="$OUTDIR/WhisperClient-mas-${VERSION}-b${BUILD}.pkg"
DESKTOP="$HOME/Desktop/WhisperClient-MAS-NO-PYTHON.pkg"
DESKTOP_ALIAS="$HOME/Desktop/WhisperClient-mas.pkg"
MAS_PROVISION="${WHISPER_MAS_PROVISION:-$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles/1c99b4c5-7eec-4cef-951c-8ba97160803b.provisionprofile}"
ARCH_FLAGS="${WHISPER_STUB_ARCH_FLAGS:--arch arm64 -arch x86_64}"
DEPLOY_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"

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

echo "=== MAS SINGLE-BINARY build ${VERSION} (${BUILD}) — без Python ==="

echo "[1/4] собрать .app (один WhisperClient Mach-O)…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp -f "$MAC/Info.plist.template" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :LSEnvironment" "$APP/Contents/Info.plist" 2>/dev/null || true

cp -f "$ROOT/packaging/VERSION" "$APP/Contents/Resources/VERSION"
cp -f "$MAC/BUNDLE_ID" "$APP/Contents/Resources/BUNDLE_ID"
cp -f "$MAC/testflight/TESTFLIGHT.md" "$APP/Contents/Resources/TESTFLIGHT.md" 2>/dev/null || true
cp -f "$MAC/reset_whisper_client_privacy.command" "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/reset_whisper_client_privacy.command"
[ -f "$ROOT/assets/AppIcon.icns" ] && cp -f "$ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

xcrun clang -O2 -Wall -Wextra -fobjc-arc $ARCH_FLAGS -mmacosx-version-min="$DEPLOY_TARGET" \
	-framework Cocoa -framework AVFoundation -framework ApplicationServices \
	-framework Carbon -framework UserNotifications \
	-o "$APP/Contents/MacOS/WhisperClient" "$MAC/WhisperClientNative.m" "$MAC/WhisperClientSettings.m" "$MAC/whisper_client_http.m"

rm -rf "$APP/Contents/Frameworks"
find "$APP/Contents/MacOS" -type f ! -name WhisperClient -delete 2>/dev/null || true
find "$APP/Contents/Resources" -name '*.py' -delete 2>/dev/null || true
find "$APP/Contents/Resources" -name '*.py' -delete 2>/dev/null || true

echo "[2/4] provision + sign…"
[ -f "$MAS_PROVISION" ] || { echo "FAIL: Mac App Store profile: $MAS_PROVISION" >&2; exit 1; }
cp -f "$MAS_PROVISION" "$APP/Contents/embedded.provisionprofile"
bash "$MAC/mas_sign_native.sh" "$APP"

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
		<key>ApplicationPath</key><string>Applications/WhisperClient.app</string>
		<key>Architectures</key><array><string>arm64</string><string>x86_64</string></array>
		<key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
		<key>CFBundleShortVersionString</key><string>${VERSION}</string>
		<key>CFBundleVersion</key><string>${BUILD}</string>
		<key>Team</key><string>Y52BT2N4L8</string>
	</dict>
	<key>ArchiveVersion</key><integer>2</integer>
	<key>CreationDate</key><date>$(date -u +"%Y-%m-%dT%H:%M:%SZ")</date>
	<key>Name</key><string>WhisperClient</string>
	<key>SchemeName</key><string>WhisperClient</string>
</dict>
</plist>
PLIST

echo "[3/4] exportArchive…"
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
rm -f "$HOME/Desktop/WhisperClient-mas-b"*.pkg "$HOME/Desktop/WhisperClient-MAS"*.pkg "$DESKTOP" "$DESKTOP_ALIAS" 2>/dev/null || true
cp -f "$FINAL" "$DESKTOP"
cp -f "$FINAL" "$DESKTOP_ALIAS"

echo "[4/4] verify…"
chmod +x "$MAC/verify_mas_pkg.sh"
bash "$MAC/verify_mas_pkg.sh" "$DESKTOP"

echo ""
echo "ГОТОВО — загружай ТОЛЬКО этот файл:"
echo "  $DESKTOP"
echo "  build ${VERSION} (${BUILD}), $(stat -f%z "$DESKTOP") bytes"
ls -la "$DESKTOP"
