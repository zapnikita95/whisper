"""Custom Vocabulary для Whisper-клиентов (Mac + Windows).

Два слоя работы со словарём:

1. Prompt-prior: строка initial_prompt / prompt отдаётся в faster-whisper и в Groq
   Whisper — она вероятностно подталкивает декодер выбирать термины из словаря
   (имена, продукты, домен). Максимум ~224 токена; мы грубо ограничиваем строку
   ~800 символами.

2. Post-replace: детерминистический слой регекс-замен, применяется к финальному
   тексту перед вставкой. Это гарантирует, что «кубернетес» → «Kubernetes», даже
   если prompt не сработал.

Файл хранения: ~/.whisper/vocab.json (единый для обеих платформ; путь задан
через expanduser, значит на Windows это %USERPROFILE%\\.whisper\\vocab.json).

Структура:
{
    "version": 1,
    "global": {
        "terms": [str, ...],
        "replacements": [{"from": <regex>, "to": <str>}, ...],
        "context_hint": str
    },
    "profiles": {
        "<AppName>": { "terms": [...], "replacements": [...], "context_hint": str },
        ...
    }
}

profiles[AppName] сматчивается по имени активного приложения, которое детектит
клиент (Mac: NSWorkspace, Windows: win32gui). Регистр имени игнорируется, точное
совпадение имеет приоритет над подстрокой.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("whisper_vocab")

_CACHE_TTL_SEC = 5.0  # достаточно, чтобы не дёргать диск, но ловить внешние правки JSON
_PROMPT_MAX_CHARS = 800  # ~224 токена в запасе

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"path": None, "mtime": 0.0, "read_at": 0.0, "data": None}


def vocab_file_path() -> str:
    base = os.path.expanduser("~/.whisper")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "vocab.json")


def default_vocab() -> dict[str, Any]:
    return {
        "version": 1,
        "global": {
            "terms": [],
            "replacements": [],
            "context_hint": "",
        },
        "profiles": {},
    }


def _ensure_shape(raw: Any) -> dict[str, Any]:
    """Приводит произвольный JSON к валидной структуре без потери данных."""
    if not isinstance(raw, dict):
        return default_vocab()
    out = default_vocab()
    g = raw.get("global") if isinstance(raw.get("global"), dict) else {}
    out["global"]["terms"] = [str(t) for t in (g.get("terms") or []) if isinstance(t, (str, int))]
    out["global"]["context_hint"] = str(g.get("context_hint") or "")
    reps = g.get("replacements") or []
    if isinstance(reps, list):
        cleaned: list[dict[str, str]] = []
        for item in reps:
            if isinstance(item, dict):
                frm = str(item.get("from") or "").strip()
                to = str(item.get("to") or "").strip()
                if frm and to:
                    cleaned.append({"from": frm, "to": to})
        out["global"]["replacements"] = cleaned
    profiles = raw.get("profiles") if isinstance(raw.get("profiles"), dict) else {}
    for name, body in profiles.items():
        if not isinstance(body, dict):
            continue
        key = str(name).strip()
        if not key:
            continue
        prof = {
            "terms": [str(t) for t in (body.get("terms") or []) if isinstance(t, (str, int))],
            "context_hint": str(body.get("context_hint") or ""),
            "replacements": [],
        }
        for item in (body.get("replacements") or []):
            if isinstance(item, dict):
                frm = str(item.get("from") or "").strip()
                to = str(item.get("to") or "").strip()
                if frm and to:
                    prof["replacements"].append({"from": frm, "to": to})
        out["profiles"][key] = prof
    return out


def ensure_vocab_file() -> str:
    """Гарантирует существование ~/.whisper/vocab.json с валидной структурой. Возвращает путь."""
    path = vocab_file_path()
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_vocab(), f, ensure_ascii=False, indent=2)
            _LOG.info("vocab_created path=%s", path)
        except OSError as e:
            _LOG.warning("vocab_create_failed err=%s", e)
    return path


def load_vocab(*, force: bool = False) -> dict[str, Any]:
    """Читает ~/.whisper/vocab.json с TTL-кэшем; повторные правки файла подхватываются по mtime."""
    path = vocab_file_path()
    now = time.time()
    with _cache_lock:
        try:
            mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
        except OSError:
            mtime = 0.0
        cached = _cache.get("data")
        if (
            not force
            and cached is not None
            and _cache.get("path") == path
            and _cache.get("mtime") == mtime
            and (now - float(_cache.get("read_at") or 0)) < _CACHE_TTL_SEC
        ):
            return cached
    ensure_vocab_file()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _LOG.warning("vocab_read_failed err=%s path=%s", e, path)
        raw = default_vocab()
    data = _ensure_shape(raw)
    with _cache_lock:
        _cache["path"] = path
        try:
            _cache["mtime"] = os.path.getmtime(path)
        except OSError:
            _cache["mtime"] = 0.0
        _cache["read_at"] = now
        _cache["data"] = data
    return data


def save_vocab(data: dict[str, Any]) -> None:
    """Сохраняет словарь на диск и сбрасывает кэш."""
    path = vocab_file_path()
    shaped = _ensure_shape(data)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(shaped, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    with _cache_lock:
        _cache["path"] = path
        try:
            _cache["mtime"] = os.path.getmtime(path)
        except OSError:
            _cache["mtime"] = 0.0
        _cache["read_at"] = time.time()
        _cache["data"] = shaped


def _match_profile_key(profiles: dict[str, Any], app_name: str | None) -> str | None:
    if not app_name:
        return None
    name = app_name.strip().lower()
    if not name:
        return None
    for key in profiles.keys():
        if key.strip().lower() == name:
            return key
    for key in profiles.keys():
        low = key.strip().lower()
        if low and (low in name or name in low):
            return key
    return None


def build_initial_prompt(
    app_name: str | None = None,
    *,
    max_chars: int = _PROMPT_MAX_CHARS,
    vocab: dict[str, Any] | None = None,
) -> str:
    """Собирает initial_prompt: global terms + profile terms + context hints.

    Пустая строка — значит клиент может НЕ передавать prompt (обратная совместимость)."""
    data = vocab if vocab is not None else load_vocab()
    g = data.get("global") or {}
    terms: list[str] = list(g.get("terms") or [])
    hint_parts: list[str] = []
    g_hint = str(g.get("context_hint") or "").strip()
    if g_hint:
        hint_parts.append(g_hint)

    profile_key = _match_profile_key(data.get("profiles") or {}, app_name)
    if profile_key:
        prof = (data.get("profiles") or {}).get(profile_key) or {}
        for t in (prof.get("terms") or []):
            if t not in terms:
                terms.append(t)
        p_hint = str(prof.get("context_hint") or "").strip()
        if p_hint:
            hint_parts.append(p_hint)

    pieces: list[str] = []
    if terms:
        pieces.append("Термины: " + ", ".join(terms) + ".")
    if hint_parts:
        pieces.append(" ".join(hint_parts))
    prompt = " ".join(pieces).strip()
    if len(prompt) > max_chars:
        prompt = prompt[: max_chars - 1].rstrip() + "…"
    return prompt


def _compile_pattern(raw: str) -> re.Pattern[str] | None:
    """Компилирует regex. Если есть \\w на границах, добавляем look-around, чтобы не ломать середину слов."""
    pattern = raw.strip()
    if not pattern:
        return None
    if not pattern.startswith("(?<") and not pattern.startswith("\\b"):
        pattern = r"(?<!\w)" + pattern
    if not pattern.endswith("(?!\\w)") and not pattern.endswith("\\b"):
        pattern = pattern + r"(?!\w)"
    try:
        return re.compile(pattern, re.IGNORECASE | re.UNICODE)
    except re.error as e:
        _LOG.warning("vocab_regex_error pattern=%r err=%s", raw, e)
        return None


def apply_replacements(
    text: str,
    app_name: str | None = None,
    *,
    vocab: dict[str, Any] | None = None,
) -> str:
    """Применяет post-regex замены из global + выбранного profile."""
    if not text:
        return text
    data = vocab if vocab is not None else load_vocab()
    out = text

    def _apply(replacements: list[dict[str, str]]) -> None:
        nonlocal out
        for item in replacements:
            frm = item.get("from") or ""
            to = item.get("to") or ""
            if not frm or not to:
                continue
            pat = _compile_pattern(frm)
            if pat is None:
                continue
            out = pat.sub(to, out)

    _apply(list((data.get("global") or {}).get("replacements") or []))
    profile_key = _match_profile_key(data.get("profiles") or {}, app_name)
    if profile_key:
        prof = (data.get("profiles") or {}).get(profile_key) or {}
        _apply(list(prof.get("replacements") or []))
    return out


def add_term(term: str, *, profile: str | None = None) -> None:
    data = load_vocab(force=True)
    term = term.strip()
    if not term:
        return
    bucket = data["global"] if not profile else data["profiles"].setdefault(
        profile, {"terms": [], "replacements": [], "context_hint": ""}
    )
    if term not in bucket["terms"]:
        bucket["terms"].append(term)
        save_vocab(data)


def add_replacement(from_pattern: str, to_text: str, *, profile: str | None = None) -> None:
    data = load_vocab(force=True)
    frm = from_pattern.strip()
    to = to_text.strip()
    if not frm or not to:
        return
    bucket = data["global"] if not profile else data["profiles"].setdefault(
        profile, {"terms": [], "replacements": [], "context_hint": ""}
    )
    for it in bucket["replacements"]:
        if it.get("from") == frm and it.get("to") == to:
            return
    bucket["replacements"].append({"from": frm, "to": to})
    save_vocab(data)


def list_terms(app_name: str | None = None) -> list[str]:
    data = load_vocab()
    terms = list((data.get("global") or {}).get("terms") or [])
    profile_key = _match_profile_key(data.get("profiles") or {}, app_name)
    if profile_key:
        prof = (data.get("profiles") or {}).get(profile_key) or {}
        for t in prof.get("terms") or []:
            if t not in terms:
                terms.append(t)
    return terms
