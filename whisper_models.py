"""
Model presets for faster-whisper (CTranslate2 layouts on Hugging Face).

Do not pass raw PyTorch weights directly to WhisperModel — use CT2 conversions
(see ru-ct2-* presets).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One downloadable / selectable Whisper model."""

    key: str
    hf_id: str
    label_en: str
    languages: tuple[str, ...]
    size_gb: float
    min_vram_gb: float
    quality: int  # 1 (fastest) … 5 (best)
    category: str  # standard | english | russian | distilled


MODEL_CATALOG: tuple[ModelSpec, ...] = (
    # —— Standard multilingual (OpenAI) ——
    ModelSpec("tiny", "tiny", "tiny — fastest, multilingual", ("multilingual",), 0.08, 0.5, 1, "standard"),
    ModelSpec("base", "base", "base — fast, multilingual", ("multilingual",), 0.15, 0.8, 2, "standard"),
    ModelSpec("small", "small", "small — balanced speed/quality", ("multilingual",), 0.50, 1.5, 3, "standard"),
    ModelSpec("medium", "medium", "medium — good quality, moderate VRAM", ("multilingual",), 1.50, 4.0, 4, "standard"),
    ModelSpec("large-v2", "large-v2", "large-v2 — high quality (legacy)", ("multilingual",), 3.00, 6.0, 4, "standard"),
    ModelSpec(
        "large-v3",
        "large-v3",
        "large-v3 — best general multilingual (RU+EN)",
        ("multilingual", "en", "ru"),
        3.10,
        6.0,
        5,
        "standard",
    ),
    # —— English-only (.en) ——
    ModelSpec("tiny.en", "tiny.en", "tiny.en — fastest English-only", ("en",), 0.08, 0.5, 1, "english"),
    ModelSpec("base.en", "base.en", "base.en — fast English-only", ("en",), 0.15, 0.8, 2, "english"),
    ModelSpec("small.en", "small.en", "small.en — balanced English", ("en",), 0.50, 1.5, 3, "english"),
    ModelSpec("medium.en", "medium.en", "medium.en — strong English, less VRAM than large", ("en",), 1.50, 4.0, 4, "english"),
    # —— Distilled / turbo ——
    ModelSpec(
        "distil-large-v3",
        "distil-large-v3",
        "distil-large-v3 — near large-v3 quality, ~6× faster",
        ("multilingual", "en"),
        1.60,
        4.0,
        4,
        "distilled",
    ),
    ModelSpec(
        "large-v3-turbo",
        "large-v3-turbo",
        "large-v3-turbo — OpenAI turbo checkpoint (fast large)",
        ("multilingual", "en"),
        1.60,
        4.0,
        4,
        "distilled",
    ),
    # —— Russian CT2 fine-tunes ——
    ModelSpec(
        "ru-ct2-pav88",
        "pav88/whisper-large-v3-russian-ct2",
        "large-v3 RU fine-tune (CT2, pav88) — best Russian on GPU",
        ("ru", "en"),
        3.10,
        6.0,
        5,
        "russian",
    ),
    ModelSpec(
        "ru-ct2-bzikst",
        "bzikst/faster-whisper-large-v3-russian",
        "large-v3 RU (CT2, bzikst) — alternative Russian build",
        ("ru", "en"),
        3.10,
        6.0,
        5,
        "russian",
    ),
    # —— Extra English-oriented HF builds ——
    ModelSpec(
        "en-ct2-systran-large-v3",
        "Systran/faster-whisper-large-v3",
        "Systran large-v3 — optimized CT2 packaging (EN-focused workflows)",
        ("en", "multilingual"),
        3.10,
        6.0,
        5,
        "english",
    ),
    ModelSpec(
        "en-ct2-systran-medium",
        "Systran/faster-whisper-medium",
        "Systran medium — English/multilingual, moderate VRAM",
        ("en", "multilingual"),
        1.50,
        4.0,
        4,
        "english",
    ),
    ModelSpec(
        "en-ct2-systran-small",
        "Systran/faster-whisper-small",
        "Systran small — light English/multilingual",
        ("en", "multilingual"),
        0.50,
        1.5,
        3,
        "english",
    ),
)

# Backward-compatible tuple: (prefs/CLI key, WhisperModel id, GUI label)
MODEL_PRESETS: tuple[tuple[str, str, str], ...] = tuple(
    (m.key, m.hf_id, m.label_en) for m in MODEL_CATALOG
)

PRESET_BY_KEY: dict[str, str] = {m.key: m.hf_id for m in MODEL_CATALOG}
SPEC_BY_KEY: dict[str, ModelSpec] = {m.key: m for m in MODEL_CATALOG}


def resolve_model(model: str) -> str:
    """Preset key or full HF org/repo → id for faster_whisper.WhisperModel."""
    s = (model or "").strip()
    if not s:
        return "large-v3"
    return PRESET_BY_KEY.get(s, s)


def preset_keys_help() -> str:
    lines = [f"  {m.key} → {m.hf_id}" for m in MODEL_CATALOG]
    return "Preset keys:\n" + "\n".join(lines)


def catalog_for_api() -> list[dict]:
    """Serialize catalog for HTTP /models."""
    return [
        {
            "key": m.key,
            "hf_id": m.hf_id,
            "label": m.label_en,
            "languages": list(m.languages),
            "size_gb": m.size_gb,
            "min_vram_gb": m.min_vram_gb,
            "quality": m.quality,
            "category": m.category,
        }
        for m in MODEL_CATALOG
    ]
