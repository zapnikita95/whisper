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


def user_data_dir(app_name: str = "WhisperHotkey") -> Path:
    """Каталог для prefs и прочих записываемых данных пользователя.

    На Windows всегда %LOCALAPPDATA%\\<app> — и для Program Files, и для portable dist,
    чтобы настройки (Groq / режим транскрипции) не терялись и не расходились с логом.
    """
    env = os.environ.get("WHISPER_USER_DATA_DIR", "").strip()
    if env:
        return Path(env)
    if sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "").strip()
        if la:
            return Path(la) / app_name
    return app_root()


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


def _writable_log_root_candidates(logger_name: str) -> list[Path]:
    """Установка в Program Files: каталог exe часто только для чтения — уводим лог в %LOCALAPPDATA%."""
    env = os.environ.get("WHISPER_LOG_DIR", "").strip()
    if env:
        return [Path(env)]
    root = app_root()
    app_name = "WhisperHotkey" if "hotkey" in logger_name else "WhisperServer"
    candidates: list[Path] = []
    if sys.platform == "win32":
        user_dir = user_data_dir(app_name)
        # Сначала user data (как prefs), потом рядом с exe — единый каталог на Win.
        candidates.append(user_dir)
        if root != user_dir:
            candidates.append(root)
    else:
        candidates.append(root)
    safe = logger_name.replace(".", "_")
    candidates.append(Path(tempfile.gettempdir()) / f"Whisper_{safe}")
    # Без дубликатов, порядок сохраняем.
    seen: set[Path] = set()
    out: list[Path] = []
    for d in candidates:
        key = d.resolve() if d.exists() else d
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _pick_writable_log_root(logger_name: str) -> Path:
    for d in _writable_log_root_candidates(logger_name):
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
    logger = logging.getLogger(name)
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh_cls = _FlushRotatingFileHandler if flush_each_record else RotatingFileHandler
    fh: logging.Handler | None = None
    path: Path | None = None
    for chosen_root in _writable_log_root_candidates(name):
        if not _try_writable_dir(chosen_root):
            continue
        candidate = chosen_root / filename
        try:
            fh = fh_cls(candidate, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            path = candidate
            _RESOLVED_LOG_ROOT = chosen_root
            break
        except OSError:
            continue
    if fh is None or path is None:
        fallback = Path(tempfile.gettempdir()) / filename
        fh = fh_cls(fallback, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        path = fallback
        _RESOLVED_LOG_ROOT = fallback.parent
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
