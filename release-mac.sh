#!/usr/bin/env bash
# Удобная точка входа из корня репозитория (в т.ч. для агента в Cursor):
# подписанный DMG + нотаризация + staple (нужны локальные whisper_*_local.env и профиль notary в связке).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/packaging/mac/release_mac_notarized.sh" "$@"
