#!/bin/bash
# Mac App Store / TestFlight — нативный клиент + локальный Parakeet (FluidAudio).
# arm64 only (Apple Silicon). Модель ~460 МБ качается при первом запуске, в pkg не кладём.
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
FLAT_PKG="$ROOT/WhisperClient-mas.pkg"
MAS_PROVISION="${WHISPER_MAS_PROVISION:-$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles/1c99b4c5-7eec-4cef-951c-8ba97160803b.provisionprofile}"
DEPLOY_TARGET="${MACOSX_DEPLOYMENT_TARGET:-14.0}"

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

echo "=== MAS Parakeet build ${VERSION} (${BUILD}) — arm64 + FluidAudio ==="

if [[ "$(uname -m)" != "arm64" ]]; then
	echo "FAIL: нужен Apple Silicon (arm64). Сейчас: $(uname -m)" >&2
	exit 1
fi

echo "[1/5] swift build (Parakeet / FluidAudio)…"
export MACOSX_DEPLOYMENT_TARGET="$DEPLOY_TARGET"
swift build -c release --package-path "$MAC" --arch arm64
BIN_DIR="$(swift build -c release --package-path "$MAC" --arch arm64 --show-bin-path)"
BIN="$BIN_DIR/WhisperClient"
[[ -x "$BIN" ]] || { echo "FAIL: нет бинарника $BIN" >&2; exit 1; }

echo "[2/5] собрать .app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Frameworks"

cp -f "$MAC/Info.plist.template" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion $DEPLOY_TARGET" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :LSEnvironment" "$APP/Contents/Info.plist" 2>/dev/null || true

cp -f "$BIN" "$APP/Contents/MacOS/WhisperClient"
chmod +x "$APP/Contents/MacOS/WhisperClient"

# Binary xcframework / dylibs рядом со swift product (NemoTextProcessing и т.п.)
shopt -s nullglob
for f in "$BIN_DIR"/*.dylib "$BIN_DIR"/*.framework; do
	base="$(basename "$f")"
	# Не тащим мусор от SPM tests
	case "$base" in
		libWhisperClient*|libFluidAudioCLI*) continue ;;
	esac
	if [[ -d "$f" ]]; then
		ditto "$f" "$APP/Contents/Frameworks/$base"
	else
		cp -f "$f" "$APP/Contents/Frameworks/$base"
		install_name_tool -change "@rpath/$base" "@executable_path/../Frameworks/$base" \
			"$APP/Contents/MacOS/WhisperClient" 2>/dev/null || true
		install_name_tool -id "@executable_path/../Frameworks/$base" \
			"$APP/Contents/Frameworks/$base" 2>/dev/null || true
	fi
done
# xcframework slices sometimes appear as nested .framework under bin
for f in "$BIN_DIR"/*.xcframework; do
	[[ -d "$f" ]] || continue
	inner="$(find "$f" -path '*/macos-arm64*/*.framework' -type d -print -quit 2>/dev/null || true)"
	[[ -n "$inner" ]] || inner="$(find "$f" -name '*.framework' -type d -print -quit 2>/dev/null || true)"
	if [[ -n "$inner" ]]; then
		base="$(basename "$inner")"
		ditto "$inner" "$APP/Contents/Frameworks/$base"
	fi
done
shopt -u nullglob

# Если Frameworks пуст — убрать (чистый static link)
if [[ -d "$APP/Contents/Frameworks" ]] && [[ -z "$(ls -A "$APP/Contents/Frameworks" 2>/dev/null || true)" ]]; then
	rmdir "$APP/Contents/Frameworks" 2>/dev/null || true
fi

cp -f "$ROOT/packaging/VERSION" "$APP/Contents/Resources/VERSION"
cp -f "$MAC/BUNDLE_ID" "$APP/Contents/Resources/BUNDLE_ID"
cp -f "$MAC/testflight/TESTFLIGHT.md" "$APP/Contents/Resources/TESTFLIGHT.md" 2>/dev/null || true
cp -f "$MAC/reset_whisper_client_privacy.command" "$APP/Contents/Resources/" 2>/dev/null || true
chmod +x "$APP/Contents/Resources/reset_whisper_client_privacy.command" 2>/dev/null || true
[ -f "$ROOT/assets/AppIcon.icns" ] && cp -f "$ROOT/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

# MAS KeepAlive agent (SMAppService) — relaunch after sandbox kill
mkdir -p "$APP/Contents/Library/LaunchAgents"
cp -f "$MAC/LaunchAgents/com.zapnikita95.WhisperClient.keepalive.plist" \
	"$APP/Contents/Library/LaunchAgents/com.zapnikita95.WhisperClient.keepalive.plist"

# rpath на Frameworks
if [[ -d "$APP/Contents/Frameworks" ]]; then
	install_name_tool -add_rpath "@executable_path/../Frameworks" "$APP/Contents/MacOS/WhisperClient" 2>/dev/null || true
fi

echo "[3/5] provision + sign…"
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
		<key>Architectures</key><array><string>arm64</string></array>
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
rm -f "$HOME/Desktop/WhisperClient-mas-b"*.pkg "$HOME/Desktop/WhisperClient-MAS"*.pkg "$DESKTOP" "$DESKTOP_ALIAS" "$FLAT_PKG" 2>/dev/null || true
cp -f "$FINAL" "$DESKTOP"
cp -f "$FINAL" "$DESKTOP_ALIAS"
cp -f "$FINAL" "$FLAT_PKG"

echo "[5/5] verify…"
chmod +x "$MAC/verify_mas_pkg.sh"
bash "$MAC/verify_mas_pkg.sh" "$DESKTOP"

echo ""
echo "ГОТОВО — загружай ТОЛЬКО этот файл:"
echo "  $DESKTOP"
echo "  (копия) $FLAT_PKG"
echo "  build ${VERSION} (${BUILD}), $(stat -f%z "$DESKTOP") bytes"
ls -la "$DESKTOP"
