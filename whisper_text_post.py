"""Shared post-STT text pipeline: spoken punctuation → vocab replacements."""
from __future__ import annotations

import re
from typing import Any

# Longer phrases first so «вопросительный знак» wins over bare «знак».
_SPOKEN_PAIRS: list[tuple[str, str]] = [
    (r"точка\s+с\s+запятой", ";"),
    (r"восклицательный\s+знак", "!"),
    (r"вопросительный\s+знак", "?"),
    (r"восклицательный", "!"),
    (r"вопросительный", "?"),
    (r"многоточие", "…"),
    (r"двоеточие", ":"),
    (r"запятая", ","),
    (r"точка", "."),
    (r"тире", "—"),
    (r"question\s+mark", "?"),
    (r"exclamation\s+(?:mark|point)", "!"),
    (r"semicolon", ";"),
    (r"colon", ":"),
    (r"ellipsis", "…"),
    (r"comma", ","),
    (r"period", "."),
    (r"full\s+stop", "."),
    (r"dash", "—"),
]


def apply_spoken_punctuation(text: str) -> str:
    """Replace spoken punctuation names (RU/EN) with symbols."""
    if not text:
        return text
    t = text
    for pattern, repl in _SPOKEN_PAIRS:
        t = re.sub(rf"(?iu)\b(?:{pattern})\b", repl, t)
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"\s*;\s*", "; ", t)
    t = re.sub(r"\s*:\s*", ": ", t)
    t = re.sub(r"\s*\.\s*", ". ", t)
    t = re.sub(r"\s*!\s*", "! ", t)
    t = re.sub(r"\s*\?\s*", "? ", t)
    t = re.sub(r"\s*…\s*", "… ", t)
    t = re.sub(r"\s*—\s*", " — ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    # Avoid trailing space after sentence enders when next is end of string
    t = re.sub(r"([.!?…])\s+$", r"\1", t)
    return t


def finalize_transcript(
    text: str,
    *,
    spoken_punctuation: bool = True,
    app_name: str | None = None,
    vocab: dict[str, Any] | None = None,
    apply_vocab: bool = True,
) -> str:
    """punct → vocab. Empty stays empty."""
    if not text:
        return text
    out = text
    if spoken_punctuation:
        out = apply_spoken_punctuation(out)
    if apply_vocab:
        try:
            from whisper_vocab import apply_replacements

            out = apply_replacements(out, app_name, vocab=vocab)
        except Exception:
            pass
    return out
