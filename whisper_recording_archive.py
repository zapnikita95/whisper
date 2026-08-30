"""Архив последних записей с микрофона (wav + метаданные)."""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

try:
    from whisper_file_log import user_data_dir
except ImportError:

    def user_data_dir(name: str = "WhisperHotkey") -> Path:
        import os

        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / name


_MAX_KEEP = 10
_LOCK = threading.Lock()
_ARCHIVE_DIR = user_data_dir("WhisperHotkey") / "recording_archive"
_INDEX_PATH = user_data_dir("WhisperHotkey") / "recording_archive.json"


def recording_archive_dir() -> Path:
    return _ARCHIVE_DIR


def recording_archive_index_path() -> Path:
    return _INDEX_PATH


def _load_items() -> list[dict[str, Any]]:
    try:
        raw = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw["items"]:
        if isinstance(item, dict) and item.get("id"):
            out.append(item)
    return out


def _write_items(items: list[dict[str, Any]]) -> None:
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _prune_files(keep_ids: set[str]) -> None:
    if not _ARCHIVE_DIR.is_dir():
        return
    for p in _ARCHIVE_DIR.glob("*.wav"):
        stem = p.stem
        if stem not in keep_ids:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def archive_age_label(ts: float) -> str:
    age = max(0, int(time.time() - ts)) if ts > 0 else 0
    if age >= 3600:
        return f"{age // 3600}ч {(age % 3600) // 60}м"
    if age >= 60:
        return f"{age // 60}м {age % 60}с"
    return f"{age}с"


def archive_item_menu_title(item: dict[str, Any], max_len: int = 56) -> str:
    ts = float(item.get("ts") or 0.0)
    dur = float(item.get("duration_sec") or 0.0)
    age = archive_age_label(ts)
    preview = str(item.get("text_preview") or "").strip().replace("\n", " ")
    if not preview:
        preview = "без текста"
    head = f"{age} · {dur:.0f}с"
    room = max_len - len(head) - 3
    if room < 8:
        return head[:max_len]
    if len(preview) > room:
        preview = preview[: room - 1] + "…"
    return f"{head}: {preview}"


def load_recording_archive(limit: int = 10) -> list[dict[str, Any]]:
    items = _load_items()
    out: list[dict[str, Any]] = []
    for item in reversed(items):
        wav = str(item.get("wav_path") or "")
        if wav and Path(wav).is_file():
            out.append(item)
        if len(out) >= limit:
            break
    return out


def push_recording(audio: Any, sample_rate: int) -> str:
    """Сохранить wav в архив (последние 10). Возвращает id записи."""
    import soundfile as sf

    with _LOCK:
        rec_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        wav_path = _ARCHIVE_DIR / f"{rec_id}.wav"
        duration_sec = float(audio.size) / float(sample_rate) if sample_rate else 0.0
        sf.write(str(wav_path), audio, int(sample_rate))
        items = _load_items()
        items.append(
            {
                "id": rec_id,
                "ts": time.time(),
                "wav_path": str(wav_path),
                "duration_sec": duration_sec,
                "sample_rate": int(sample_rate),
                "text_preview": "",
            }
        )
        if len(items) > _MAX_KEEP:
            items = items[-_MAX_KEEP:]
        keep_ids = {str(x.get("id") or "") for x in items}
        _prune_files(keep_ids)
        _write_items(items)
        root = user_data_dir("WhisperHotkey")
        root.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(wav_path), str(root / "last_recording.wav"))
            (root / "last_recording.json").write_text(
                json.dumps(
                    {
                        "ts": time.time(),
                        "duration_sec": duration_sec,
                        "sample_rate": int(sample_rate),
                        "id": rec_id,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        return rec_id


def update_recording_transcript(rec_id: str, text: str, *, max_preview: int = 120) -> None:
    rid = (rec_id or "").strip()
    if not rid:
        return
    preview = (text or "").strip().replace("\n", " ")
    if len(preview) > max_preview:
        preview = preview[: max_preview - 1] + "…"
    with _LOCK:
        items = _load_items()
        for item in items:
            if str(item.get("id") or "") == rid:
                item["text_preview"] = preview
                item["transcript_chars"] = len((text or "").strip())
                break
        _write_items(items)


def get_recording_by_id(rec_id: str) -> dict[str, Any] | None:
    rid = (rec_id or "").strip()
    if not rid:
        return None
    for item in _load_items():
        if str(item.get("id") or "") == rid:
            wav = str(item.get("wav_path") or "")
            if wav and Path(wav).is_file():
                return item
    return None
