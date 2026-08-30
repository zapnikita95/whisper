"""Очередь неотправленных записей (повтор распознавания без новой диктовки)."""
from __future__ import annotations

import json
import shutil
import threading
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


_PENDING_LOCK = threading.Lock()
_PENDING_DIR = user_data_dir("WhisperHotkey") / "pending_audio"
_PENDING_INDEX = user_data_dir("WhisperHotkey") / "pending_transcriptions.json"


def pending_audio_dir() -> Path:
    return _PENDING_DIR


def pending_index_path() -> Path:
    return _PENDING_INDEX


def pending_item_age_label(ts: float) -> str:
    age = max(0, int(time.time() - ts)) if ts > 0 else 0
    if age >= 3600:
        return f"{age // 3600}ч {(age % 3600) // 60}м назад"
    if age >= 60:
        return f"{age // 60}м {age % 60}с назад"
    return f"{age}с назад"


def pending_item_menu_title(item: dict[str, Any], max_len: int = 52) -> str:
    ts = float(item.get("ts") or 0.0)
    age = pending_item_age_label(ts)
    reason = str(item.get("reason") or "").strip()
    if reason.startswith("connection:"):
        reason = "нет связи"
    elif reason.startswith("timeout:"):
        reason = "таймаут"
    elif reason.startswith("error:"):
        reason = reason[6:].strip() or "ошибка"
    elif reason.startswith("groq_http_403"):
        reason = "403 Groq"
    reason = " ".join(reason.split())
    if len(reason) > 36:
        reason = reason[:35] + "…"
    title = f"{age}: {reason}" if reason else age
    if len(title) > max_len:
        return title[: max_len - 1] + "…"
    return title


def load_pending_transcriptions(limit: int = 50) -> list[dict[str, Any]]:
    path = _PENDING_INDEX
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw["items"]:
        if not isinstance(item, dict):
            continue
        wav = str(item.get("wav_path") or "").strip()
        if not wav:
            continue
        try:
            ts = float(item.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        out.append(
            {
                "id": str(item.get("id") or ""),
                "ts": ts,
                "wav_path": wav,
                "reason": str(item.get("reason") or ""),
                "route": str(item.get("route") or ""),
            }
        )
    out.sort(key=lambda x: float(x.get("ts") or 0.0), reverse=True)
    return out[:limit]


def _save_pending_transcriptions(items: list[dict[str, Any]]) -> None:
    path = _PENDING_INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def enqueue_pending_transcription(wav_path: str, *, reason: str, route: str) -> dict[str, Any]:
    src = Path(wav_path)
    if not src.is_file():
        raise FileNotFoundError(str(src))
    with _PENDING_LOCK:
        d = _PENDING_DIR
        d.mkdir(parents=True, exist_ok=True)
        ts = time.time()
        rid = f"{int(ts * 1000)}"
        dst = d / f"pending_{rid}.wav"
        shutil.copy2(src, dst)
        cur = load_pending_transcriptions(limit=500)
        item = {
            "id": rid,
            "ts": ts,
            "wav_path": str(dst),
            "reason": reason[:240],
            "route": route[:120],
        }
        cur.insert(0, item)
        cur = cur[:200]
        _save_pending_transcriptions(cur)
        return item


def remove_pending_transcription(item_id: str) -> None:
    kill = (item_id or "").strip()
    if not kill:
        return
    with _PENDING_LOCK:
        cur = load_pending_transcriptions(limit=500)
        kept: list[dict[str, Any]] = []
        for it in cur:
            if str(it.get("id") or "") == kill:
                p = Path(str(it.get("wav_path") or ""))
                try:
                    if p.is_file():
                        p.unlink()
                except OSError:
                    pass
                continue
            kept.append(it)
        _save_pending_transcriptions(kept)


def clear_pending_transcriptions() -> None:
    for item in load_pending_transcriptions(limit=500):
        rid = str(item.get("id") or "")
        if rid:
            remove_pending_transcription(rid)
