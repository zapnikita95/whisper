#!/bin/bash
# Запускай из обычного Терминала.app (не из фона агента): один раз ввести пароль связки «Вход»,
# разблокировать её и собрать подписанный WhisperClient.app — без зависания codesign на GUI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOGIN_KC="${HOME}/Library/Keychains/login.keychain-db"

read -rsp "Пароль связки ключей «Вход» (часто как пароль входа в Mac): " KC_PASS
echo ""

if [ -f "$LOGIN_KC" ]; then
	security unlock-keychain -p "$KC_PASS" "$LOGIN_KC"
fi

export WHISPER_LOGIN_KEYCHAIN_PASSWORD="$KC_PASS"
exec bash "$ROOT/packaging/mac/build_signed_app.sh"
