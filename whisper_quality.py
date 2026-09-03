"""Stable STT quality: always large-class decode + punctuated prompt.

Whisper copies the style of `initial_prompt` / Groq `prompt`. An empty prompt
or a vocab list without sentence punctuation makes large-v3 drop commas and
periods — that is why dictation quality jumped around even on large-v3.
int8-only decode makes it worse; int8_float16 / float16 keeps the decoder in FP16.
"""
from __future__ import annotations

import os
from typing import Any, Callable

# Bilingual punctuated seed. Must contain commas, periods, ? ! so the decoder
# keeps producing them. Keep this short: vocab terms still need room (~800 chars).
PUNCTUATION_PROMPT_SEED = (
    "Здравствуйте. Это диктовка с пунктуацией: запятые, точки, вопросительные знаки? Да! "
    "Hello, this is a well-punctuated transcript."
)

_PROMPT_MAX_CHARS = 800


def merge_initial_prompt(*parts: str | None, max_chars: int = _PROMPT_MAX_CHARS) -> str:
    """Always start with the punctuation seed, then optional vocab / hints."""
    chunks: list[str] = []
    seen: set[str] = set()

    def _add(raw: str | None) -> None:
        t = (raw or "").strip()
        if not t or t in seen:
            return
        seen.add(t)
        chunks.append(t)

    seed = PUNCTUATION_PROMPT_SEED.strip()
    _add(seed)
    for part in parts:
        s = (part or "").strip()
        if not s:
            continue
        if s.startswith(seed):
            rest = s[len(seed) :].strip()
            _add(rest)
        elif seed in s:
            _add(s.replace(seed, " ").strip())
        else:
            _add(s)
    out = " ".join(chunks).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 1].rstrip() + "…"
    return out


def resolve_dictation_beam_size(*, audio_sec: float | None = None) -> int:
    """Hotkey dictation: beam 1 is ~3–5× faster on GPU with near-identical quality.

    Keep beam 5 for long files / server batch (explicit env wins).
    """
    raw = (os.environ.get("WHISPER_BEAM_SIZE") or "").strip()
    if raw:
        try:
            return max(1, min(int(raw), 10))
        except ValueError:
            pass
    if audio_sec is not None and float(audio_sec) > 90.0:
        return 5
    # Default for Ctrl+Win clips: prefer latency.
    return 1


def local_transcribe_kwargs(
    *,
    language: str | None = None,
    initial_prompt: str | None = None,
    audio_sec: float | None = None,
    beam_size: int | None = None,
) -> dict[str, Any]:
    """Decode settings shared by Hotkey GPU and HTTP server."""
    beam = beam_size if beam_size is not None else resolve_dictation_beam_size(audio_sec=audio_sec)
    kwargs: dict[str, Any] = {
        "beam_size": beam,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "without_timestamps": True,
        "initial_prompt": merge_initial_prompt(initial_prompt),
    }
    if language:
        kwargs["language"] = language
    return kwargs


def resolve_quality_compute_type(
    *,
    device: str,
    explicit: str | None = None,
) -> str:
    """Prefer FP16 decoder on CUDA. Explicit env/prefs win; `auto` uses VRAM."""
    raw = (explicit or "").strip().lower()
    if raw and raw not in ("auto",):
        return raw
    if (device or "").strip().lower() != "cuda":
        return "int8"
    try:
        from whisper_system_profile import nvidia_vram_snapshot

        snap = nvidia_vram_snapshot()
        total = snap.get("vram_total_gb")
        free = snap.get("vram_free_gb")
        gb = free if free is not None else total
        if gb is not None and float(gb) >= 10:
            return "float16"
    except Exception:
        pass
    return "int8_float16"


def resolve_hotkey_compute_type(device: str = "cuda") -> str:
    """Env → default quality compute for the Windows hotkey / server."""
    explicit = (os.environ.get("WHISPER_COMPUTE_TYPE") or "").strip()
    return resolve_quality_compute_type(device=device, explicit=explicit or None)


def load_whisper_model(
    name: str,
    *,
    device: str,
    compute_type: str,
    log_warning: Callable[..., None] | None = None,
) -> tuple[Any, str]:
    """Load faster-whisper; if high-precision CUDA compute fails, retry int8."""
    from faster_whisper import WhisperModel

    try:
        return WhisperModel(name, device=device, compute_type=compute_type), compute_type
    except Exception as e:
        fallback = "int8"
        if (
            (device or "").strip().lower() == "cuda"
            and (compute_type or "").strip().lower() in {"float16", "int8_float16", "float32"}
            and (compute_type or "").strip().lower() != fallback
        ):
            if log_warning:
                log_warning(
                    "compute_type=%s failed (%s) — retry %s",
                    compute_type,
                    e,
                    fallback,
                )
            return WhisperModel(name, device=device, compute_type=fallback), fallback
        raise


def strip_prompt_echo(text: str, *, prompt: str | None = None) -> str:
    """Drop Whisper copies of the punctuation seed when there was no real speech."""
    t = (text or "").strip()
    if not t:
        return ""
    seed = PUNCTUATION_PROMPT_SEED.strip()
    low = t.lower().strip(" .")
    if low in {
        seed.lower().strip(" ."),
        "hello, this is a well-punctuated transcript",
        "здравствуйте. это диктовка с пунктуацией: запятые, точки, вопросительные знаки? да",
    }:
        return ""
    if t.startswith(seed) and len(t) <= len(seed) + 8:
        return ""
    if prompt:
        p = prompt.strip()
        if p and t == p:
            return ""
    return t


def ai_rewrite_available() -> bool:
    """LLM polish/chat/code needs a live Groq path (key or reachable Cloud proxy)."""
    try:
        from whisper_groq import groq_rewrite_ready

        return bool(groq_rewrite_ready())
    except Exception:
        return False
