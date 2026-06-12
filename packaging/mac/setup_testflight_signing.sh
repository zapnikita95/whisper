#!/bin/bash
# Один раз перед TestFlight: Apple Distribution + Mac App Store profile для WhisperClient.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUNDLE_ID="$(tr -d ' \n\r' <"$ROOT/packaging/mac/BUNDLE_ID")"

echo "=== Whisper Client → TestFlight: проверка подписи ==="
echo "Bundle ID: $BUNDLE_ID"
echo ""

has_dist=false
if security find-identity -v -p codesigning 2>/dev/null | grep -q "Apple Distribution"; then
	has_dist=true
	echo "✓ Apple Distribution certificate найден"
else
	echo "✗ Apple Distribution certificate НЕ найден"
	echo "  Xcode → Settings → Accounts → Nikita Zaporozhets → Manage Certificates → + → Apple Distribution"
fi

profile=""
for pf in "$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"/*.provisionprofile; do
	[ -f "$pf" ] || continue
	if security cms -D -i "$pf" 2>/dev/null | grep -q "$BUNDLE_ID"; then
		profile="$pf"
		break
	fi
done

if [ -n "$profile" ]; then
	echo "✓ Mac App Store profile: $profile"
else
	echo "✗ Mac App Store profile для $BUNDLE_ID не найден"
	echo "  developer.apple.com → Profiles → + → Mac App Store → App ID $BUNDLE_ID → Download"
	echo "  (Xcode сам положит в UserData/Provisioning Profiles)"
fi

echo ""
if $has_dist && [ -n "$profile" ]; then
	echo "Готово к сборке:"
	echo "  bash packaging/mac/build_mas_pkg.sh"
	echo "  bash packaging/mac/upload_testflight.sh"
else
	echo "После сертификата и profile — команды выше."
	open "https://developer.apple.com/account/resources/profiles/add" 2>/dev/null || true
fi

echo ""
echo "Важно: Mac App Store (sandbox) может ограничить глобальные хоткеи (Fn)."
echo "Developer ID .app / DMG — полный функционал (рекомендуется для диктовки)."
