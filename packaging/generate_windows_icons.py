#!/usr/bin/env python3
"""Генерирует assets/hotkey_icon.ico и assets/server_icon.ico (разные цвета/буквы для панели задач)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def _save_ico(path: Path, rgb_bg: tuple[int, int, int], letter: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    sizes = [16, 24, 32, 48, 64, 256]
    images: list[Image.Image] = []
    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        margin = max(1, sz // 16)
        draw.rounded_rectangle(
            [margin, margin, sz - margin - 1, sz - margin - 1],
            radius=max(2, sz // 8),
            fill=rgb_bg + (255,),
        )
        try:
            font = ImageFont.truetype("segoeui.ttf", max(sz // 2, 8))
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), letter, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((sz - tw) // 2, (sz - th) // 2 - bbox[1]),
            letter,
            fill=(255, 255, 255, 255),
            font=font,
        )
        images.append(img)
    images[0].save(path, format="ICO", sizes=[(im.width, im.height) for im in images])


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    # Hotkey: зелёный, H (Ctrl+Win локально)
    _save_ico(ASSETS / "hotkey_icon.ico", (32, 110, 75), "H")
    # Сервер: синий, S (HTTP API)
    _save_ico(ASSETS / "server_icon.ico", (25, 85, 165), "S")
    # Совместимость со старыми скриптами: общий app_icon = hotkey
    try:
        import shutil

        shutil.copyfile(ASSETS / "hotkey_icon.ico", ASSETS / "app_icon.ico")
    except OSError:
        pass
    print("OK:", ASSETS / "hotkey_icon.ico", ASSETS / "server_icon.ico", ASSETS / "app_icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
