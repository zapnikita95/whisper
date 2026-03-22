"""Единая версия приложения: packaging/VERSION или переменная окружения WHISPER_VERSION (CI)."""
from __future__ import annotations

import os
from pathlib import Path


def get_version() -> str:
    env = (os.environ.get("WHISPER_VERSION") or "").strip()
    if env:
        return env
    here = Path(__file__).resolve().parent
    for rel in ("packaging/VERSION", "VERSION"):
        p = here / rel
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return "0.0.0-dev"


__version__ = get_version()
