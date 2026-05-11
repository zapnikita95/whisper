# shellcheck shell=bash
# Подключается из run.sh и start-client-mac.command: source …/pick_python_for_whisper.sh
_whisper_mac_prepend_path() {
	export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
}

# Путь ведёт на Python Launcher / IDLE / pythonw — не использовать (всплывает лишнее GUI).
_whisper_mac_reject_python_path() {
	local p="$1"
	local rp base
	[ -z "$p" ] && return 0
	base="$(basename "$p")"
	case "$base" in
	pythonw|pythonw3|idle|idle3) return 0 ;;
	esac
	rp="$p"
	if command -v realpath >/dev/null 2>&1; then
		rp="$(realpath "$p" 2>/dev/null || echo "$p")"
	fi
	_rl="$(printf '%s' "$rp" | tr '[:upper:]' '[:lower:]')"
	case "$_rl" in
	*python*launcher*|*idle.app*|*"python launcher"*)
		return 0
		;;
	esac
	return 1
}

# python3 → python3.13 / python3.12 в том же каталоге (реальный Mach-O, без оболочек python.org).
_whisper_mac_prefer_versioned_python() {
	local dir base try
	dir="$(dirname "$1")"
	base="$(basename "$1")"
	case "$base" in
	python3|python)
		for try in "$dir/python3.13" "$dir/python3.12" "$dir/python3.11" "$dir/python3.10"; do
			if [ -x "$try" ]; then
				echo "$try"
				return 0
			fi
		done
		;;
	esac
	echo "$1"
}

# Python 3.13 + pynput < 1.8 → клиент сразу exit(1); .app «молча» не поднимается, если первый в PATH старый pynput.
_whisper_mac_pynput_ok_for_py313() {
	local py="$1"
	"$py" -c "
import sys
try:
    from importlib.metadata import version as pkg_version
except ImportError:
    raise SystemExit(0)
if sys.version_info < (3, 13):
    raise SystemExit(0)
raw = pkg_version('pynput')
nums = []
for part in raw.split('.')[:3]:
    digits = ''.join(ch for ch in part if ch.isdigit())
    nums.append(int(digits) if digits else 0)
while len(nums) < 3:
    nums.append(0)
raise SystemExit(0 if tuple(nums) >= (1, 8, 0) else 1)
" 2>/dev/null
}

# Первый python3, в котором реально стоят зависимости клиента (Finder часто видит «голый» /usr/bin/python3).
pick_python_for_whisper() {
	local cands x seen c fallback pv
	_whisper_mac_prepend_path
	if [ -n "${WHISPER_PYTHON3:-}" ] && [ -x "${WHISPER_PYTHON3}" ]; then
		if ! _whisper_mac_reject_python_path "${WHISPER_PYTHON3}"; then
			pv="$(_whisper_mac_prefer_versioned_python "${WHISPER_PYTHON3}")"
			if ! _whisper_mac_reject_python_path "$pv" && \
				"$pv" -c "import requests, sounddevice, numpy, soundfile, pynput, pyperclip" 2>/dev/null && \
				_whisper_mac_pynput_ok_for_py313 "$pv"; then
				echo "$pv"
				return 0
			fi
		fi
	fi
	# Из .app: сначала python.org (туда обычно ставят pip install rumps), иначе часто берётся Homebrew без rumps → нет иконки.
	# Явные python3.X — меньше шансов всплытия Python Launcher, чем общий python3.
	# Сначала Homebrew/usr/local: тот же интерпретатор, что у «Терминал + .command» → те же права
	# «Универсальный доступ» для pynput. Framework Python — отдельное приложение в списке TCC.
	if [ "${WHISPER_MAC_APP_PICK_PYTHON:-}" = "1" ]; then
		cands=(
			"/opt/homebrew/bin/python3.13"
			"/opt/homebrew/bin/python3.12"
			"/opt/homebrew/bin/python3.11"
			"/opt/homebrew/bin/python3"
			"/usr/local/bin/python3.13"
			"/usr/local/bin/python3.12"
			"/usr/local/bin/python3.11"
			"/usr/local/bin/python3"
			"$HOME/Library/Python/3.13/bin/python3"
			"$HOME/Library/Python/3.12/bin/python3"
			"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"
			"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
			"/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
			"/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
			"/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11"
			"/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
		)
	else
		cands=(
			"/opt/homebrew/bin/python3.13"
			"/opt/homebrew/bin/python3.12"
			"/opt/homebrew/bin/python3"
			"/usr/local/bin/python3.13"
			"/usr/local/bin/python3.12"
			"/usr/local/bin/python3"
			"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"
			"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
			"/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
			"/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
			"$HOME/Library/Python/3.13/bin/python3"
			"$HOME/Library/Python/3.12/bin/python3"
		)
	fi
	x="$(command -v python3 2>/dev/null || true)"
	[ -n "$x" ] && cands+=("$x")
	cands+=("/usr/bin/python3")
	seen=""
	for c in "${cands[@]}"; do
		[ -z "$c" ] && continue
		[ ! -x "$c" ] && continue
		case " $seen " in *" $c "*) continue ;; esac
		seen="$seen $c"
		if _whisper_mac_reject_python_path "$c"; then
			continue
		fi
		pv="$(_whisper_mac_prefer_versioned_python "$c")"
		if _whisper_mac_reject_python_path "$pv"; then
			continue
		fi
		if "$pv" -c "import requests, sounddevice, numpy, soundfile, pynput, pyperclip" 2>/dev/null; then
			if ! _whisper_mac_pynput_ok_for_py313 "$pv"; then
				continue
			fi
			if [ -z "$fallback" ]; then
				fallback="$pv"
			fi
			if "$pv" -c "import rumps" 2>/dev/null; then
				echo "$pv"
				return 0
			fi
		fi
	done
	if [ -n "$fallback" ]; then
		echo "$fallback"
		return 0
	fi
	return 1
}
