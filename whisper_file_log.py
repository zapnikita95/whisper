"""Ротационные логи рядом с exe / в каталоге приложения (отладка)."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED: set[str] = set()


class _FlushRotatingFileHandler(RotatingFileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


class _FlushFileHandler(logging.FileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def log_dir() -> Path:
    raw = os.environ.get("WHISPER_LOG_DIR", "").strip()
    if raw:
        return Path(raw)
    return app_root()


def configure(
    name: str,
    filename: str,
    *,
    level: int = logging.DEBUG,
    flush_each_record: bool = False,
    mirror_temp_basename: str | None = None,
) -> logging.Logger:
    """
    Один файл на процесс: whisper_server.log / whisper_hotkey.log в WHISPER_LOG_DIR или рядом с exe.
    flush_each_record — сразу сбрасывать на диск (удобно, пока идёт долгий импорт CUDA/CT2).
    mirror_temp_basename — второй лог в %TEMP% (имя файла), чтобы быстро найти без поиска рядом с exe.
    """
    if name in _CONFIGURED:
        return logging.getLogger(name)
    _CONFIGURED.add(name)

    log_dir().mkdir(parents=True, exist_ok=True)
    path = log_dir() / filename
    logger = logging.getLogger(name)
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh_cls = _FlushRotatingFileHandler if flush_each_record else RotatingFileHandler
    fh = fh_cls(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if mirror_temp_basename:
        tp = Path(tempfile.gettempdir()) / mirror_temp_basename
        try:
            mh = _FlushFileHandler(tp, mode="a", encoding="utf-8")
            mh.setLevel(level)
            mh.setFormatter(fmt)
            logger.addHandler(mh)
        except OSError:
            pass

    # У windowed PyInstaller stderr часто «ломаный»; запись в него из фонового потока может подвиснуть.
    err = getattr(sys, "stderr", None)
    if err is not None and getattr(err, "write", None) is not None:
        try:
            sh = logging.StreamHandler(err)
            sh.setLevel(logging.INFO)
            sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            logger.addHandler(sh)
        except OSError:
            pass

    logger.debug("Лог: %s", path.resolve())
    return logger
