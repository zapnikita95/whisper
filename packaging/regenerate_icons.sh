#!/bin/bash
# Пересобрать assets/AppIcon.icns и assets/app_icon.ico из assets/app_icon.png (macOS + Pillow).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/assets/app_icon.png"
if [ ! -f "$SRC" ]; then
	echo "Нет $SRC"
	exit 1
fi
ICONSET="$ROOT/assets/AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
	sips -z "$s" "$s" "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
done
sips -z 32 32 "$SRC" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 64 64 "$SRC" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 256 256 "$SRC" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 512 512 "$SRC" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 1024 1024 "$SRC" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET" -o "$ROOT/assets/AppIcon.icns"
rm -rf "$ICONSET"
python3 -c "
from pathlib import Path
from PIL import Image
img = Image.open('$SRC').convert('RGBA')
sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
img.save('$ROOT/assets/app_icon.ico', format='ICO', sizes=sizes)
print('ICO OK')
"
echo "Готово: assets/AppIcon.icns, assets/app_icon.ico"
