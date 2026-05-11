#!/usr/bin/env bash
# Полный релиз: подписанный DMG → нотаризация Apple → stapler.
# Разово перед первым запуском: bash packaging/mac/notary_store_credentials.sh
#
# Из корня репозитория:
#   bash packaging/mac/release_mac_notarized.sh
# С версией DMG:
#   bash packaging/mac/release_mac_notarized.sh 1.2.19
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

bash packaging/mac/release_mac_signed.sh "$@"
bash packaging/mac/notarize_and_staple_dmg.sh
