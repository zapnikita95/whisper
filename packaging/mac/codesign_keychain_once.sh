#!/bin/bash
# Одноразовая настройка: после успешного ввода пароля связки «Вход» macOS чаще
# перестаёт дёргать codesign на каждую подпись (partition list для apple-tool/codesign).
#
# «Недействительная метка» / бесконечные запросы часто лечатся перезагрузкой и этим шагом.
# Полностью без пароля закрытый ключ выдать нельзя — это политика Apple.
#
# Использование:
#   bash packaging/mac/codesign_keychain_once.sh
# или пароль из env (осторожно, в shell history):
#   KEYCHAIN_PASSWORD='…' bash packaging/mac/codesign_keychain_once.sh

set -euo pipefail
KEYCHAIN="${HOME}/Library/Keychains/login.keychain-db"

if [ ! -f "$KEYCHAIN" ]; then
	echo "Не найдена связка: $KEYCHAIN"
	exit 1
fi

if [ -z "${KEYCHAIN_PASSWORD:-}" ]; then
	echo "Введи пароль связки ключей «Вход» (часто = пароль входа в этот Mac;"
	echo "если менял пароль пользователя — попробуй старый)."
	read -rsp "Пароль: " KEYCHAIN_PASSWORD
	echo ""
fi

security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"

# Разрешить инструментам Apple и codesign использовать ключи из связки без ACL-пинга.
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN"

echo "Готово. Перезапусти Terminal/Cursor и снова: bash packaging/mac/build_signed_app.sh"
echo "Если снова «недействительная метка» — перезагрузи Mac и повтори этот скрипт один раз."
