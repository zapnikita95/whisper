#!/usr/bin/env python3
"""Собирает app_icon.ico / hotkey_icon.ico / server_icon.ico из assets/app_icon.png (как раньше)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SRC_PNG = ASSETS / "app_icon.png"
SRC_ICO = ASSETS / "app_icon.ico"


def _ico_from_png(png: Path, ico: Path) -> None:
    from PIL import Image

    img = Image.open(png).convert("RGBA")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ico, format="ICO", sizes=[(w, h) for w, h in sizes])


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    if SRC_PNG.is_file():
        _ico_from_png(SRC_PNG, SRC_ICO)
    elif not SRC_ICO.is_file():
        print("Нужен assets/app_icon.png или assets/app_icon.ico", file=sys.stderr)
        return 1
    for name in ("hotkey_icon.ico", "server_icon.ico"):
        shutil.copyfile(SRC_ICO, ASSETS / name)
    print("OK:", SRC_ICO, ASSETS / "hotkey_icon.ico", ASSETS / "server_icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
