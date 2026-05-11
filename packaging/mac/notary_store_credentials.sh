#!/usr/bin/env bash
# Один раз: сохранить учётку notarytool в связке ключей (после этого пароль не нужен в командах submit).
# Нужен файл packaging/mac/whisper_notary_local.env — см. whisper_notary_local.env.example
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV="$ROOT/packaging/mac/whisper_notary_local.env"
if [ ! -f "$ENV" ]; then
	echo "Создай файл $ENV"
	echo "  cp packaging/mac/whisper_notary_local.env.example packaging/mac/whisper_notary_local.env"
	echo "и впиши WHISPER_NOTARY_APP_PASSWORD (пароль приложения с appleid.apple.com)."
	exit 1
fi
set -a
# shellcheck disable=SC1091
source "$ENV"
set +a

PROFILE="${WHISPER_NOTARY_PROFILE:-whisper-notary}"
xcrun notarytool store-credentials "$PROFILE" \
	--apple-id "${WHISPER_NOTARY_APPLE_ID}" \
	--team-id "${WHISPER_NOTARY_TEAM_ID}" \
	--password "${WHISPER_NOTARY_APP_PASSWORD}"

echo "Готово: профиль «${PROFILE}» сохранён в связке. Дальше: bash packaging/mac/notarize_and_staple_dmg.sh"
