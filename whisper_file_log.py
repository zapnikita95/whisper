"""Ротационные логи рядом с exe / в каталоге приложения (отладка)."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED: set[str] = set()

# После первого configure() — каталог, куда реально пишется лог (важно для записи из Program Files).
_RESOLVED_LOG_ROOT: Path | None = None


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
    """Каталог логов: после configure() совпадает с тем, куда удалось записать файл."""
    global _RESOLVED_LOG_ROOT
    if _RESOLVED_LOG_ROOT is not None:
        return _RESOLVED_LOG_ROOT
    raw = os.environ.get("WHISPER_LOG_DIR", "").strip()
    if raw:
        return Path(raw)
    return app_root()


def _try_writable_dir(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".whisper_log_probe"
        probe.write_text("ok", encoding="ascii")
        probe.unlink(missing_ok=True)
        # Реальный лог — как при RotatingFileHandler; probe мог пройти из‑за странных ACL.
        real = d / ".whisper_log_probe_real.log"
        try:
            with real.open("a", encoding="ascii") as f:
                f.write("")
        finally:
            real.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _is_windows_program_files_tree(p: Path) -> bool:
    """Каталог установки под Program Files — обычному пользователю часто нельзя создавать *.log."""
    try:
        resolved = p.resolve()
    except OSError:
        return False
    low = {part.lower() for part in resolved.parts}
    return "program files" in low or "program files (x86)" in low


def _pick_writable_log_root(logger_name: str) -> Path:
    """Установка в Program Files: каталог exe часто только для чтения — уводим лог в %LOCALAPPDATA%."""
    env = os.environ.get("WHISPER_LOG_DIR", "").strip()
    if env:
        return Path(env)
    root = app_root()
    candidates: list[Path] = []
    if sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "").strip()
        la_sub = (
            Path(la)
            / ("WhisperHotkey" if "hotkey" in logger_name else "WhisperServer")
            if la
            else None
        )
        restricted = _is_windows_program_files_tree(root)
        if restricted:
            # Не предлагаем Program Files — даже если mkdir/probe прошли, *.log часто запрещён политикой.
            if la_sub is not None:
                candidates.append(la_sub)
        else:
            candidates.append(root)
            if la_sub is not None:
                candidates.append(la_sub)
    else:
        candidates.append(root)
    safe = logger_name.replace(".", "_")
    candidates.append(Path(tempfile.gettempdir()) / f"Whisper_{safe}")
    for d in candidates:
        if _try_writable_dir(d):
            return d
    return Path(tempfile.gettempdir())


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

    global _RESOLVED_LOG_ROOT
    chosen_root = _pick_writable_log_root(name)
    _RESOLVED_LOG_ROOT = chosen_root
    path = chosen_root / filename
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
