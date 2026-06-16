"""Transcription history for Windows Whisper Hotkey (parity with Mac client)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    from whisper_file_log import user_data_dir
except ImportError:

    def user_data_dir(name: str = "WhisperHotkey") -> Path:
        import os

        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / name


HISTORY_PATH = user_data_dir("WhisperHotkey") / "transcription_history.json"
_MAX_STORE = 500


def _ensure_dir() -> None:
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def load_history(limit: int = 200) -> list[dict[str, Any]]:
    _ensure_dir()
    try:
        raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[-limit:]:
        if isinstance(item, dict) and item.get("text"):
            out.append(item)
    return list(reversed(out))


def append_history(text: str, *, failure: bool = False) -> None:
    line = (text or "").strip()
    if not line:
        return
    _ensure_dir()
    try:
        cur: list[dict[str, Any]] = []
        if HISTORY_PATH.is_file():
            raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                cur = raw
        cur.append(
            {
                "text": line,
                "ts": time.time(),
                "failure": bool(failure),
            }
        )
        if len(cur) > _MAX_STORE:
            cur = cur[-_MAX_STORE:]
        HISTORY_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def preview_title(text: str, max_len: int = 56) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"
