"""AI rewrite modes after STT (email / chat / code / translate / polish)."""
from __future__ import annotations

import json
import os
from typing import Any, Callable

import requests

ALLOWED_AI_MODES = frozenset(
    {"raw", "polish", "email", "chat", "code", "translate_en", "translate_ru"}
)
# Prefs may also store "auto" (context from frontmost app).
ALLOWED_AI_MODE_PREFS = ALLOWED_AI_MODES | {"auto"}
FREE_CLOUD_AI_MODES = frozenset({"raw", "polish"})
PRO_AI_MODES = ALLOWED_AI_MODES

DEFAULT_CHAT_MODEL = "llama-3.3-70b-versatile"

_MODE_SYSTEM: dict[str, str] = {
    "polish": (
        "You clean up speech-to-text. Fix grammar and punctuation. "
        "Keep the same language as the input. Do not add greetings or commentary. "
        "Return only the cleaned text."
    ),
    "email": (
        "Rewrite the dictated text as a clear professional email body. "
        "Keep the user's language. Add a short greeting and sign-off only if natural. "
        "Return only the email text, no subject line unless the user asked for one."
    ),
    "chat": (
        "Rewrite the dictated text as a concise friendly chat message. "
        "Keep the user's language. No hashtags. Return only the message."
    ),
    "code": (
        "The user dictated programming-related text. Format it as clean code or a "
        "precise technical note. Prefer the language they imply. Return only the result."
    ),
    "translate_en": (
        "Translate the text to natural English. Return only the translation."
    ),
    "translate_ru": (
        "Translate the text to natural Russian. Return only the translation."
    ),
}

_MODE_LABELS_RU: dict[str, str] = {
    "auto": "Авто (по приложению)",
    "raw": "Как есть (без AI)",
    "polish": "Зачистка",
    "email": "Письмо",
    "chat": "Чат",
    "code": "Код / техзаметка",
    "translate_en": "→ English",
    "translate_ru": "→ Русский",
}


class AiModeProRequired(RuntimeError):
    """Cloud free plan cannot use this mode."""

    def __init__(self, mode: str):
        super().__init__(
            f"Режим «{_MODE_LABELS_RU.get(mode, mode)}» доступен в Whisper Cloud Pro "
            "(или со своим ключом Groq / локальным GPU)."
        )
        self.mode = mode


def normalize_ai_mode(raw: str | None) -> str:
    m = (raw or "auto").strip().lower()
    if m in ALLOWED_AI_MODE_PREFS:
        return m
    return "auto"


def mode_label(mode: str) -> str:
    m = normalize_ai_mode(mode)
    return _MODE_LABELS_RU.get(m, m)


def cloud_plan_allows_mode(
    mode: str,
    plan: str | None,
    *,
    has_byok: bool,
    local_stt_ok: bool = False,
) -> bool:
    if mode == "auto":
        return True
    mode = mode if mode in ALLOWED_AI_MODES else "raw"
    if mode == "raw":
        return True
    if has_byok or local_stt_ok:
        return True
    if (plan or "free").lower() == "pro":
        return True
    return mode in FREE_CLOUD_AI_MODES


def read_hotkey_ai_mode_pref() -> str:
    try:
        from whisper_groq import load_hotkey_prefs

        v = load_hotkey_prefs().get("ai_mode")
        if isinstance(v, str) and v.strip():
            return normalize_ai_mode(v)
    except Exception:
        pass
    return "auto"


# (regex, mode) — longer phrases first
_VOICE_PREFIXES: list[tuple[str, str]] = [
    (r"^(?:переведи\s+на\s+английск\w*|translate\s+to\s+english|translate\s+into\s+english)\s+", "translate_en"),
    (r"^(?:переведи\s+на\s+русск\w*|translate\s+to\s+russian|translate\s+into\s+russian)\s+", "translate_ru"),
    (r"^(?:переведи|translate)\s+", "translate_en"),
    (r"^(?:как\s+код|как\s+code|code\s*[:\-]?)\s+", "code"),
    (r"^(?:письмо|email|e-mail)\s+", "email"),
    (r"^(?:чат|chat|сообщение)\s+", "chat"),
    (r"^(?:зачистка|polish|почисти)\s+", "polish"),
    (r"^(?:просто|как\s+есть|raw)\s+", "raw"),
]


def strip_voice_prefix(text: str) -> tuple[str, str | None]:
    """Return (text_without_prefix, mode_or_None)."""
    import re

    t = (text or "").strip()
    if not t:
        return t, None
    for pat, mode in _VOICE_PREFIXES:
        m = re.match(pat, t, flags=re.IGNORECASE | re.UNICODE)
        if m:
            rest = t[m.end() :].strip()
            return rest, mode
    return t, None


def resolve_effective_mode(
    text: str,
    *,
    app_name: str | None,
    pref_mode: str | None = None,
    allow_auto_context: bool = True,
    free_fallback: str = "polish",
) -> tuple[str, str]:
    """Strip voice prefix + resolve mode. Returns (clean_text, mode)."""
    clean, prefix_mode = strip_voice_prefix(text)
    if prefix_mode:
        return clean, prefix_mode
    pref = normalize_ai_mode(pref_mode)
    if pref != "auto" and pref in ALLOWED_AI_MODES:
        return clean, pref
    if allow_auto_context:
        from whisper_app_context import suggest_ai_mode

        return clean, suggest_ai_mode(app_name, free_fallback=free_fallback)
    return clean, "raw"


def clamp_mode_for_plan(
    mode: str,
    plan: str | None,
    *,
    has_byok: bool,
    local_stt_ok: bool = False,
) -> str:
    """If mode not allowed, fall back to polish then raw."""
    if cloud_plan_allows_mode(mode, plan, has_byok=has_byok, local_stt_ok=local_stt_ok):
        return mode if mode in ALLOWED_AI_MODES else "raw"
    if cloud_plan_allows_mode("polish", plan, has_byok=has_byok, local_stt_ok=local_stt_ok):
        return "polish"
    return "raw"


def post_groq_chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    timeout: tuple[float, float] = (30.0, 90.0),
    pref_api_key: str | None = None,
    pref_proxy_url: str | None = None,
    pref_proxy_secret: str | None = None,
    pref_proxy_enabled: bool | None = None,
    pref_cloud_token: str | None = None,
    log_error: Callable[..., None] | None = None,
) -> str:
    from whisper_groq import (
        DEFAULT_GROQ_PROXY_URL,
        ensure_cloud_token_for_proxy,
        groq_api_key_from_env,
        resolve_cloud_token,
        resolve_groq_api_key,
        resolve_groq_proxy_enabled,
        resolve_groq_proxy_secret,
        resolve_groq_proxy_url,
    )

    proxy_enabled = resolve_groq_proxy_enabled(pref_proxy_enabled)
    proxy_base = resolve_groq_proxy_url(pref_proxy_url) if proxy_enabled else ""
    use_proxy = bool(proxy_base)
    url = (
        f"{proxy_base}/openai/v1/chat/completions"
        if use_proxy
        else "https://api.groq.com/openai/v1/chat/completions"
    )
    key = resolve_groq_api_key(pref_api_key) or groq_api_key_from_env()
    proxy_secret = resolve_groq_proxy_secret(pref_proxy_secret) if proxy_enabled else ""
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "WhisperClient/1.0 (AI Modes)",
    }
    if proxy_secret:
        headers["X-Whisper-Groq-Proxy-Secret"] = proxy_secret
    passthrough = (os.environ.get("WHISPER_GROQ_PROXY_PASSTHROUGH_AUTH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if key and (not use_proxy or passthrough):
        headers["Authorization"] = f"Bearer {key}"
    elif not use_proxy:
        raise ValueError("Нужен GROQ_API_KEY для AI Modes без прокси.")

    if use_proxy and not passthrough and not (key and passthrough):
        if not proxy_secret or resolve_cloud_token(pref_cloud_token):
            try:
                tok = ensure_cloud_token_for_proxy(proxy_base or DEFAULT_GROQ_PROXY_URL, pref_token=pref_cloud_token)
                headers["X-Whisper-Cloud-Token"] = tok
            except Exception as e:
                if not proxy_secret and not key:
                    raise RuntimeError(f"AI Modes: нет Cloud токена / ключа: {e}") from e

    body = {
        "model": (model or os.environ.get("WHISPER_AI_MODE_MODEL") or DEFAULT_CHAT_MODEL).strip(),
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=timeout)
    if resp.status_code >= 400:
        detail = (resp.text or "")[:400]
        if log_error:
            log_error("ai_mode_chat_http status=%s body=%r", resp.status_code, detail)
        raise RuntimeError(f"ai_mode_http_{resp.status_code}:{detail}")
    out = resp.json()
    try:
        content = out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("ai_mode_bad_response") from e
    return (content or "").strip()


def apply_ai_mode(
    text: str,
    mode: str,
    *,
    cloud_plan: str | None = None,
    has_byok: bool = False,
    local_stt_ok: bool = False,
    pref_api_key: str | None = None,
    pref_proxy_url: str | None = None,
    pref_proxy_secret: str | None = None,
    pref_proxy_enabled: bool | None = None,
    pref_cloud_token: str | None = None,
    log_error: Callable[..., None] | None = None,
) -> str:
    """Rewrite text according to mode. raw returns unchanged."""
    mode = normalize_ai_mode(mode)
    text = (text or "").strip()
    if not text or mode == "raw":
        return text
    if not cloud_plan_allows_mode(
        mode, cloud_plan, has_byok=has_byok, local_stt_ok=local_stt_ok
    ):
        raise AiModeProRequired(mode)
    system = _MODE_SYSTEM.get(mode)
    if not system:
        return text
    return post_groq_chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        pref_api_key=pref_api_key,
        pref_proxy_url=pref_proxy_url,
        pref_proxy_secret=pref_proxy_secret,
        pref_proxy_enabled=pref_proxy_enabled,
        pref_cloud_token=pref_cloud_token,
        log_error=log_error,
    )


def resolve_cloud_plan_for_gate(
    *,
    pref_cloud_token: str | None = None,
    pref_proxy_url: str | None = None,
) -> str | None:
    """Best-effort plan from /v1/me; None if unknown."""
    try:
        from whisper_groq import (
            DEFAULT_GROQ_PROXY_URL,
            fetch_cloud_me,
            resolve_cloud_token,
            resolve_groq_proxy_url,
        )

        tok = resolve_cloud_token(pref_cloud_token)
        if not tok:
            return None
        base = resolve_groq_proxy_url(pref_proxy_url) or DEFAULT_GROQ_PROXY_URL
        me = fetch_cloud_me(base, tok)
        plan = me.get("plan")
        return str(plan) if plan else "free"
    except Exception:
        return None
