#!/bin/bash
# MAS 409: venv/bin/* и WhisperRuntime — только shell (не Mach-O).
# Запуск: MacOS/whisper_python (Mach-O без sandbox → наследует контейнер .app).
set -euo pipefail
APP="${1:?WhisperClient.app}"
FW="$APP/Contents/Frameworks/WhisperRuntime.framework"
VENV="$FW/Resources/venv"
WP="$APP/Contents/MacOS/whisper_python"
STUB="$APP/Contents/Frameworks/Python.framework/Versions/3.13/bin/python3.13"

[ -f "$STUB" ] || { echo "FAIL: нет $STUB" >&2; exit 1; }

_adhoc_sign() {
	codesign -s - -f "$1" 2>/dev/null || true
}

cp -f "$STUB" "$WP"
chmod +x "$WP"
OLD="/Library/Frameworks/Python.framework/Versions/3.13/Python"
NEW='@loader_path/../Frameworks/Python.framework/Versions/3.13/Python'
for _old in "$OLD" '@loader_path/../Python' '@loader_path/../../../../Python' \
	'@loader_path/../../../../Python.framework/Versions/3.13/Python'; do
	install_name_tool -change "$_old" "$NEW" "$WP" 2>/dev/null || true
done
_adhoc_sign "$WP"

_wrapper() {
	local dest="$1"
	cat >"$dest" <<'WRAP'
#!/bin/bash
set -euo pipefail
_BIN="$(cd "$(dirname "$0")" && pwd)"
_PY="$(cd "$_BIN/../../../../../MacOS" && pwd)/whisper_python"
_RT_FW="$(cd "$_BIN/../../.." && pwd)"
export PYTHONHOME="$_RT_FW/../Python.framework/Versions/3.13"
_SITE="$(cd "$_BIN/.." && pwd)/lib/python3.13/site-packages"
[ -d "$_SITE" ] && export PYTHONPATH="$_SITE${PYTHONPATH:+:$PYTHONPATH}"
exec "$_PY" "$@"
WRAP
	chmod +x "$dest"
	_adhoc_sign "$dest"
}

for _n in python3.13 python3 python; do
	rm -f "$VENV/bin/$_n"
	_wrapper "$VENV/bin/$_n"
done

cat >"$FW/WhisperRuntime" <<'WRAP'
#!/bin/bash
set -euo pipefail
_RT_FW="$(cd "$(dirname "$0")" && pwd)"
_PY="$(cd "$_RT_FW/../../MacOS" && pwd)/whisper_python"
export PYTHONHOME="$_RT_FW/../Python.framework/Versions/3.13"
_SITE="$_RT_FW/Resources/venv/lib/python3.13/site-packages"
[ -d "$_SITE" ] && export PYTHONPATH="$_SITE${PYTHONPATH:+:$PYTHONPATH}"
exec "$_PY" "$@"
WRAP
chmod +x "$FW/WhisperRuntime"
_adhoc_sign "$FW/WhisperRuntime"

export PYTHONHOME="$APP/Contents/Frameworks/Python.framework/Versions/3.13"
export PYTHONPATH="$VENV/lib/python3.13/site-packages"
"$VENV/bin/python3.13" -c "import rumps; print('mas launcher ok')" || {
	echo "FAIL: venv wrapper" >&2
	exit 1
}
echo "  ✓ MAS shell wrappers + whisper_python OK"
