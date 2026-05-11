# Подключается из packaging/build_mac_app.sh — не запускать напрямую.
# Ожидает переменную MAC (каталог packaging/mac).

unset WHISPER_MAC_CODESIGN_IDENTITY 2>/dev/null || true

ENV_FILE="${MAC}/whisper_codesign_local.env"
if [ -f "$ENV_FILE" ]; then
	set -a
	# shellcheck disable=SC1091
	source "$ENV_FILE"
	set +a
fi

export WHISPER_MAC_CODESIGN_IDENTITY="${WHISPER_MAC_CODESIGN_IDENTITY:-Developer ID Application: Nikita Zaporozhets (Y52BT2N4L8)}"

if [ -z "${WHISPER_LOGIN_KEYCHAIN_PASSWORD:-}" ] && [ -n "${WHISPER_LOGIN_KEYCHAIN_PASSWORD_CMD:-}" ]; then
	WHISPER_LOGIN_KEYCHAIN_PASSWORD="$(bash -c "${WHISPER_LOGIN_KEYCHAIN_PASSWORD_CMD}" 2>/dev/null || true)"
	export WHISPER_LOGIN_KEYCHAIN_PASSWORD
fi

LOGIN_KC="${HOME}/Library/Keychains/login.keychain-db"
if [ -n "${WHISPER_LOGIN_KEYCHAIN_PASSWORD:-}" ] && [ -f "$LOGIN_KC" ]; then
	security unlock-keychain -p "$WHISPER_LOGIN_KEYCHAIN_PASSWORD" "$LOGIN_KC" 2>/dev/null || true
fi
