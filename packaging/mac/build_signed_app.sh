#!/bin/bash
# Тонкая обёртка: всегда Developer ID (как packaging/mac/build_mac_app.sh + whisper_codesign_prepare.sh).
# Для повседневной работы достаточно whisper_codesign_local.env + обычный build_mac_app.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export WHISPER_CODESIGN_PREPARE_MODE=always
exec bash "$ROOT/packaging/build_mac_app.sh"
