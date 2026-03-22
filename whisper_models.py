"""
Пресеты моделей для faster-whisper (репозитории с раскладкой CTranslate2 на Hugging Face).

Сырые веса PyTorch (например antony66/whisper-large-v3-russian) напрямую в WhisperModel не подставлять —
нужна CT2-конверсия (см. пресеты ru-ct2-*).
"""
from __future__ import annotations

# (ключ для prefs/CLI, id для WhisperModel(), подпись в GUI)
MODEL_PRESETS: tuple[tuple[str, str, str], ...] = (
    (
        "large-v3",
        "large-v3",
        "large-v3 — оригинал (RU+EN), мало настроек",
    ),
    (
        "ru-ct2-pav88",
        "pav88/whisper-large-v3-russian-ct2",
        "large-v3 RU fine-tune (CT2, pav88) — тот же finetune, что antony66, в формате faster-whisper",
    ),
    (
        "ru-ct2-bzikst",
        "bzikst/faster-whisper-large-v3-russian",
        "large-v3 RU (CT2, bzikst) — альтернативная сборка на HF",
    ),
)

PRESET_BY_KEY: dict[str, str] = {k: mid for k, mid, _ in MODEL_PRESETS}


def resolve_model(model: str) -> str:
    """Ключ пресета или полный HF/org/repo → id для faster_whisper.WhisperModel."""
    s = (model or "").strip()
    if not s:
        return "large-v3"
    return PRESET_BY_KEY.get(s, s)


def preset_keys_help() -> str:
    lines = [f"  {k} → {mid}" for k, mid, _ in MODEL_PRESETS]
    return "Ключи пресетов:\n" + "\n".join(lines)
