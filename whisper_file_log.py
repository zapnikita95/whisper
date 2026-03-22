"""Ротационные логи рядом с exe / в каталоге приложения (отладка)."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED: set[str] = set()


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def log_dir() -> Path:
    raw = os.environ.get("WHISPER_LOG_DIR", "").strip()
    if raw:
        return Path(raw)
    return app_root()


def configure(name: str, filename: str, *, level: int = logging.DEBUG) -> logging.Logger:
    """
    Один файл на процесс: whisper_server.log / whisper_hotkey.log в WHISPER_LOG_DIR или рядом с exe.
    """
    if name in _CONFIGURED:
        return logging.getLogger(name)
    _CONFIGURED.add(name)

    log_dir().mkdir(parents=True, exist_ok=True)
    path = log_dir() / filename
    logger = logging.getLogger(name)
    logger.setLevel(level)
    fh = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"),
    )
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)

    logger.debug("Лог: %s", path.resolve())
    return logger
