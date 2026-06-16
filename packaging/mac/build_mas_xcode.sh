#!/bin/bash
# УСТАРЕЛО: Python/venv MAS pipeline (409/90238/SIGTRAP).
# Используй: bash packaging/mac/build_mas_native.sh
echo "⚠️  build_mas_xcode.sh устарел (Python → 409/crash)." >&2
echo "    Запускаю build_mas_native.sh …" >&2
exec "$(cd "$(dirname "$0")" && pwd)/build_mas_native.sh" "$@"
