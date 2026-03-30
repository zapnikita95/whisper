#!/usr/bin/env bash
# Упаковка WhisperClient.app в DMG (нужен brew install create-dmg).
# Использование: ./packaging/mac/make_dmg.sh [версия]
# По умолчанию версия читается из packaging/VERSION.
#
# По умолчанию СНАЧАЛА вызывается packaging/build_mac_app.sh — иначе DMG мог бы содержать
# устаревший .app («из DMG всё другое, чем свежий packaging/mac»).
# Пропустить пересборку: WHISPER_DMG_SKIP_APP_BUILD=1 ./packaging/mac/make_dmg.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="${1:-$(tr -d '\r\n' < "$ROOT/packaging/VERSION")}"
APP="$ROOT/packaging/mac/WhisperClient.app"
OUTDIR="$ROOT/dist/release"
DMG="$OUTDIR/WhisperClient-${VERSION}.dmg"

if ! command -v create-dmg >/dev/null 2>&1; then
	echo "Установи create-dmg: brew install create-dmg" >&2
	exit 1
fi

if [ "${WHISPER_DMG_SKIP_APP_BUILD:-}" != "1" ]; then
	echo "Пересборка $APP (WHISPER_DMG_SKIP_APP_BUILD=1 чтобы пропустить)…" >&2
	( cd "$ROOT" && bash packaging/build_mac_app.sh )
else
	echo "Пропуск build_mac_app.sh (WHISPER_DMG_SKIP_APP_BUILD=1)" >&2
fi

if [ ! -d "$APP" ]; then
	echo "Нет $APP после сборки." >&2
	exit 1
fi

mkdir -p "$OUTDIR"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/whisper-dmg.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
cp -R "$APP" "$STAGING/"
# Ссылку на /Applications добавляет сам create-dmg (--app-drop-link); второй ln даёт «File exists».

rm -f "$DMG"
create-dmg \
	--volname "Whisper Client ${VERSION}" \
	--window-pos 200 120 \
	--window-size 660 420 \
	--icon-size 88 \
	--icon "WhisperClient.app" 180 200 \
	--hide-extension "WhisperClient.app" \
	--app-drop-link 480 200 \
	"$DMG" \
	"$STAGING"

echo "Готово: $DMG"
