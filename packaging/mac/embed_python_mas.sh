#!/bin/bash
# MAS/TestFlight: venv --copies всё равно линкуется на /Library/Frameworks/Python.framework → crash в sandbox.
set -euo pipefail
APP="${1:?WhisperClient.app}"
VENV="${2:?path to venv inside WhisperRuntime.framework/Resources/venv}"
SRC="${WHISPER_BUNDLE_PYTHON_FRAMEWORK:-/Library/Frameworks/Python.framework}/Versions/${WHISPER_BUNDLE_PYTHON_VERSION:-3.13}"
DEST_FW="$APP/Contents/Frameworks/Python.framework"
DEST="$DEST_FW/Versions/3.13"
OLD="/Library/Frameworks/Python.framework/Versions/3.13/Python"
NEW_VENV='@loader_path/../../../../Python.framework/Versions/3.13/Python'
NEW_PYAPP='@loader_path/../../../../Python'
NEW_BIN='@loader_path/../Python'

[ -f "$SRC/Python" ] || { echo "FAIL: нет $SRC/Python (python.org 3.13?)" >&2; exit 1; }
[ -d "$SRC/Resources/Python.app" ] || { echo "FAIL: нет $SRC/Resources/Python.app" >&2; exit 1; }

echo "MAS embed Python.framework (~70MB stdlib)…"
rm -rf "$DEST_FW"
mkdir -p "$DEST/lib/python3.13" "$DEST/bin" "$DEST/Resources"

cp -f "$SRC/Python" "$DEST/Python"
chmod +x "$DEST/Python"
cp -f "$SRC/Resources/Info.plist" "$DEST/Resources/Info.plist"
rsync -a "$SRC/Resources/Python.app/" "$DEST/Resources/Python.app/"
for py in python3.13 python3 python; do
	[ -f "$SRC/bin/$py" ] && cp -f "$SRC/bin/$py" "$DEST/bin/$py" && chmod +x "$DEST/bin/$py"
done

rsync -a \
	--exclude='site-packages' \
	--exclude='test' \
	--exclude='tests' \
	--exclude='__pycache__' \
	--exclude='idlelib' \
	--exclude='tkinter' \
	--exclude='turtledemo' \
	--exclude='config-3.13-darwin' \
	"$SRC/lib/python3.13/" "$DEST/lib/python3.13/"

mkdir -p "$DEST_FW/Versions"
ln -sf "3.13" "$DEST_FW/Versions/Current"
ln -sf "Versions/Current/Python" "$DEST_FW/Python"
ln -sf "Versions/Current/Resources" "$DEST_FW/Resources"

_adhoc_sign() {
	codesign -s - -f "$1" 2>/dev/null || true
}

_fix_link() {
	local f="$1" new="$2"
	install_name_tool -change "$OLD" "$new" "$f" 2>/dev/null || true
	_adhoc_sign "$f"
}

install_name_tool -id "@rpath/Python.framework/Versions/3.13/Python" "$DEST/Python" 2>/dev/null || true
_adhoc_sign "$DEST/Python"

PYAPP="$DEST/Resources/Python.app/Contents/MacOS/Python"
_fix_link "$PYAPP" "$NEW_PYAPP"

for py in python3.13 python3 python; do
	_f="$DEST/bin/$py"
	[ -f "$_f" ] && _fix_link "$_f" "$NEW_BIN"
done

for py in python3.13 python3 python; do
	_f="$VENV/bin/$py"
	[ -f "$_f" ] || continue
	_fix_link "$_f" "$NEW_VENV"
done

cat >"$VENV/pyvenv.cfg" <<CFG
home = ../../../../Python.framework/Versions/3.13
include-system-site-packages = false
version = 3.13.5
executable = ../../../../Python.framework/Versions/3.13/bin/python3.13
command = MAS embedded Python.framework
CFG

if otool -L "$VENV/bin/python3.13" 2>/dev/null | grep -q '/Library/Frameworks/Python.framework'; then
	echo "FAIL: python3.13 всё ещё ссылается на /Library/Frameworks" >&2
	otool -L "$VENV/bin/python3.13" >&2 | head -6
	exit 1
fi
[ -x "$PYAPP" ] || { echo "FAIL: нет $PYAPP" >&2; exit 1; }

export PYTHONHOME="$DEST"
if ! "$VENV/bin/python3.13" -c "import sys, rumps; print('embed ok', sys.version_info[:2])" 2>&1; then
	echo "FAIL: embedded python не стартует" >&2
	exit 1
fi
echo "  ✓ embedded python import ok"
