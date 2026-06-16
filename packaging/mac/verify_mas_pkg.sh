#!/bin/bash
# Жёсткая проверка перед Transporter — ловит старый Python-пакет.
set -euo pipefail
PKG="${1:-$HOME/Desktop/WhisperClient-MAS-NO-PYTHON.pkg}"
[ -f "$PKG" ] || PKG="$HOME/Desktop/WhisperClient-mas.pkg"
[ -f "$PKG" ] || { echo "FAIL: нет pkg: $PKG" >&2; exit 1; }

TMP="/tmp/whisper_mas_verify_$$"
rm -rf "$TMP"
pkgutil --expand-full "$PKG" "$TMP"
APP=$(find "$TMP" -path '*/Payload/WhisperClient.app' -type d -print -quit 2>/dev/null)
[ -n "$APP" ] || { echo "FAIL: нет WhisperClient.app в pkg" >&2; exit 1; }

FAIL=0
SIZE=$(stat -f%z "$PKG" 2>/dev/null || stat -c%s "$PKG")
BUILD=$(plutil -extract CFBundleVersion raw "$APP/Contents/Info.plist" 2>/dev/null || echo "?")
VERSION=$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist" 2>/dev/null || echo "?")

echo "=== MAS pkg verify ==="
echo "  file: $PKG"
echo "  size: $SIZE bytes ($(echo "scale=2; $SIZE/1048576" | bc) MB)"
echo "  version: $VERSION (build $BUILD)"

if [ "$SIZE" -gt 3000000 ]; then
	echo "  ✗ СЛИШКОМ БОЛЬШОЙ — похоже на старый Python-пакет (>3MB)" >&2
	FAIL=1
fi

if [ -d "$APP/Contents/Frameworks" ]; then
	echo "  ✗ ЕСТЬ Frameworks/ — это Python-сборка, НЕ загружать" >&2
	find "$APP/Contents/Frameworks" -type f 2>/dev/null | head -10 >&2
	FAIL=1
else
	echo "  ✓ нет Frameworks/"
fi

BAD=$(find "$APP" \( -iname '*python*' -o -iname '*WhisperRuntime*' -o -name '*.py' \) 2>/dev/null | head -5)
if [ -n "$BAD" ]; then
	echo "  ✗ найден Python-мусор:" >&2
	echo "$BAD" >&2
	FAIL=1
else
	echo "  ✓ нет python/WhisperRuntime/.py"
fi

MACOS=$(find "$APP/Contents/MacOS" -type f 2>/dev/null | sort)
COUNT=$(echo "$MACOS" | grep -c . || echo 0)
echo "  MacOS файлы ($COUNT):"
echo "$MACOS" | sed 's/^/    /'
if [ "$COUNT" -ne 1 ] || [ ! -f "$APP/Contents/MacOS/WhisperClient" ]; then
	echo "  ✗ должен быть ТОЛЬКО MacOS/WhisperClient" >&2
	FAIL=1
else
	echo "  ✓ один бинарник WhisperClient"
fi

if ! codesign -d --entitlements :- "$APP/Contents/MacOS/WhisperClient" 2>/dev/null | grep -q 'com.apple.security.app-sandbox'; then
	echo "  ✗ нет app-sandbox на WhisperClient" >&2
	FAIL=1
else
	echo "  ✓ sandbox на WhisperClient"
fi

if ! codesign --verify --deep --strict "$APP" 2>/dev/null; then
	echo "  ✗ codesign verify failed" >&2
	FAIL=1
else
	echo "  ✓ codesign OK"
fi

rm -rf "$TMP"
if [ "$FAIL" -ne 0 ]; then
	echo "" >&2
	echo "НЕ ЗАГРУЖАЙ ЭТОТ PKG В TRANSPORTER." >&2
	exit 1
fi
echo ""
echo "OK — можно загружать в Transporter (build $BUILD, native, без Python)."
