#!/bin/bash
# Создаёт .venv в корне репозитория и ставит зависимости Mac-клиента.
# Запуск: из любого места — ./packaging/mac/setup_mac_venv.sh
#   или: bash packaging/mac/setup_mac_venv.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PY="${1:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
	echo "Ошибка: не найден интерпретатор «$PY». Укажи: $0 /usr/local/bin/python3.13" >&2
	exit 1
fi

echo "Репозиторий: $ROOT"
echo "Базовый Python: $($PY -c 'import sys; print(sys.executable)')"

if [ ! -d "$ROOT/.venv" ]; then
	echo "Создаю .venv …"
	"$PY" -m venv "$ROOT/.venv"
else
	echo "Уже есть $ROOT/.venv — обновляю пакеты."
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -U pip wheel
pip install -r "$ROOT/packaging/requirements-mac-client.txt"

echo ""
echo "Готово."
echo "  Python: $ROOT/.venv/bin/python3"
"$ROOT/.venv/bin/python3" -c "import rumps, pynput; from importlib.metadata import version as v; print('  pynput', v('pynput'))"
echo ""
echo "Запуск клиента из репо: ./start-client-mac.command"
echo "Сборка .app: ./packaging/build_mac_app.sh — run.sh сам подхватит .venv, если лежит рядом с packaging/mac/WhisperClient.app"
