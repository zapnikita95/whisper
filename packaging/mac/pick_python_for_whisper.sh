# shellcheck shell=bash
# Подключается из run.sh и start-client-mac.command: source …/pick_python_for_whisper.sh
_whisper_mac_prepend_path() {
	export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
}

# Первый python3, в котором реально стоят зависимости клиента (Finder часто видит «голый» /usr/bin/python3).
pick_python_for_whisper() {
	_whisper_mac_prepend_path
	if [ -n "${WHISPER_PYTHON3:-}" ] && [ -x "${WHISPER_PYTHON3}" ]; then
		if "${WHISPER_PYTHON3}" -c "import requests, sounddevice, numpy, soundfile, pynput, pyperclip" 2>/dev/null; then
			echo "${WHISPER_PYTHON3}"
			return 0
		fi
	fi
	local cands=(
		"/opt/homebrew/bin/python3"
		"/usr/local/bin/python3"
		"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
		"/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
		"/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
		"$HOME/Library/Python/3.13/bin/python3"
		"$HOME/Library/Python/3.12/bin/python3"
	)
	local x
	x="$(command -v python3 2>/dev/null || true)"
	[ -n "$x" ] && cands+=("$x")
	cands+=("/usr/bin/python3")
	local seen="" c fallback=""
	for c in "${cands[@]}"; do
		[ -z "$c" ] && continue
		[ ! -x "$c" ] && continue
		case " $seen " in *" $c "*) continue ;; esac
		seen="$seen $c"
		if "$c" -c "import requests, sounddevice, numpy, soundfile, pynput, pyperclip" 2>/dev/null; then
			if [ -z "$fallback" ]; then
				fallback="$c"
			fi
			if "$c" -c "import rumps" 2>/dev/null; then
				echo "$c"
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
