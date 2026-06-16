"""
Check Hugging Face cache and pre-download Whisper CT2 weights.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable

from whisper_models import MODEL_CATALOG, SPEC_BY_KEY, resolve_model

_DOWNLOAD_LOCK = threading.Lock()
_ACTIVE: dict[str, str] = {}  # key -> status: queued|downloading|done|error


def hf_cache_root() -> Path:
    import os

    env = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "huggingface" / "hub"


def _repo_folder_name(hf_id: str) -> str:
    # models--Systran--faster-whisper-large-v3
    return "models--" + hf_id.replace("/", "--")


def is_model_cached(model_key: str) -> bool:
    spec = SPEC_BY_KEY.get(model_key)
    if spec is None:
        hf_id = resolve_model(model_key)
    else:
        hf_id = spec.hf_id

    # OpenAI sizes ship inside faster-whisper package cache too
    if "/" not in hf_id:
        try:
            from faster_whisper.utils import download_model

            path = download_model(hf_id, local_files_only=True)
            return Path(path).is_dir()
        except Exception:
            pass

    folder = hf_cache_root() / _repo_folder_name(hf_id)
    if not folder.is_dir():
        return False
    # Any snapshot with model.bin or *.safetensors
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix in (".bin", ".safetensors", ".json"):
            if p.name in ("config.json", "tokenizer.json") or "model" in p.name.lower():
                return True
    return any(folder.rglob("model.bin")) or any(folder.rglob("*.safetensors"))


def download_status(model_key: str) -> str | None:
    return _ACTIVE.get(model_key)


def download_model(
    model_key: str,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Download weights; raises on failure. Thread-safe per key."""
    spec = SPEC_BY_KEY.get(model_key)
    if spec is None:
        raise ValueError(f"Unknown model key: {model_key}")
    hf_id = spec.hf_id

    def prog(msg: str) -> None:
        _ACTIVE[model_key] = msg
        if on_progress:
            on_progress(msg)

    with _DOWNLOAD_LOCK:
        _ACTIVE[model_key] = "downloading"
        try:
            prog(f"Downloading {hf_id}…")
            if "/" in hf_id:
                from huggingface_hub import snapshot_download

                path = snapshot_download(repo_id=hf_id)
                prog("done")
                _ACTIVE[model_key] = "done"
                return Path(path)
            from faster_whisper.utils import download_model as fw_download

            path = fw_download(hf_id)
            prog("done")
            _ACTIVE[model_key] = "done"
            return Path(path)
        except Exception as e:
            _ACTIVE[model_key] = f"error: {e}"
            raise
        finally:
            if _ACTIVE.get(model_key) == "downloading":
                _ACTIVE.pop(model_key, None)


def models_status_for_api() -> list[dict]:
    out = []
    for m in MODEL_CATALOG:
        st = download_status(m.key)
        out.append(
            {
                "key": m.key,
                "cached": is_model_cached(m.key),
                "download_status": st,
            }
        )
    return out


def safe_repo_id(hf_id: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?$", hf_id or ""))
