"""AI rewrite modes after STT (email / chat / code / translate / polish)."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

import requests

ALLOWED_AI_MODES = frozenset(
    {"raw", "polish", "email", "chat", "code", "translate_en", "translate_ru"}
)
# Prefs may also store "auto" (context from frontmost app).
ALLOWED_AI_MODE_PREFS = ALLOWED_AI_MODES | {"auto"}
FREE_CLOUD_AI_MODES = frozenset({"raw", "polish"})
PRO_AI_MODES = ALLOWED_AI_MODES

# Groq retired llama-3.3-70b-versatile / llama-3.1-8b-instant on 2026-08-16.
DEFAULT_CHAT_MODEL = "openai/gpt-oss-120b"
FALLBACK_CHAT_MODELS = (
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
)

_MODE_SYSTEM: dict[str, str] = {
    "polish": (
        "You clean up speech-to-text. Fix grammar. Keep or restore punctuation "
        "(commas, periods, question marks, exclamation marks). Never strip punctuation. "
        "If the input has almost none, add natural sentence punctuation. "
        "Keep the same language as the input. Do not add greetings or commentary. "
        "Return only the cleaned text."
    ),
    "email": (
        "Rewrite the dictated text as a clear professional email body. "
        "Keep the user's language. Use normal punctuation. "
        "Add a short greeting and sign-off only if natural. "
        "Return only the email text, no subject line unless the user asked for one."
    ),
    "chat": (
        "Rewrite the dictated text as a concise friendly chat message. "
        "Keep the user's language. Keep all punctuation — commas, periods, "
        "question marks. Do not flatten the text into a punctuation-free dump. "
        "No hashtags. Return only the message."
    ),
    "code": (
        "The user dictated programming-related text. Format it as clean code or a "
        "precise technical note. Prefer the language they imply. "
        "If the input is natural speech (a prompt, comment, or explanation), "
        "keep it as prose with normal punctuation — do not strip commas and periods. "
        "Return only the result."
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


class AiModeUnavailable(RuntimeError):
    """Proxy/network down — caller should keep raw STT text."""


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
    timeout: tuple[float, float] = (3.0, 25.0),
    pref_api_key: str | None = None,
    pref_proxy_url: str | None = None,
    pref_proxy_secret: str | None = None,
    pref_proxy_enabled: bool | None = None,
    pref_cloud_token: str | None = None,
    log_error: Callable[..., None] | None = None,
) -> str:
    from whisper_groq import (
        PROXY_CONNECT_DEADLINE_SEC,
        ensure_cloud_token_for_proxy,
        groq_api_key_from_env,
        groq_proxy_url_candidates,
        http_call_deadline,
        is_proxy_cold_start_response,
        is_proxy_unreachable,
        mark_proxy_reachable,
        mark_proxy_unreachable,
        _is_layero_proxy,
        resolve_cloud_token,
        resolve_groq_api_key,
        resolve_groq_proxy_enabled,
        resolve_groq_proxy_secret,
    )

    proxy_enabled = resolve_groq_proxy_enabled(pref_proxy_enabled)
    key = resolve_groq_api_key(pref_api_key) or groq_api_key_from_env()
    proxy_secret = resolve_groq_proxy_secret(pref_proxy_secret) if proxy_enabled else ""
    passthrough = (os.environ.get("WHISPER_GROQ_PROXY_PASSTHROUGH_AUTH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    def _build_headers(proxy_base: str) -> dict[str, str]:
        hdrs: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "WhisperClient/1.0 (AI Modes)",
        }
        if proxy_secret:
            hdrs["X-Whisper-Groq-Proxy-Secret"] = proxy_secret
        if proxy_base:
            if key and passthrough:
                hdrs["Authorization"] = f"Bearer {key}"
            elif not passthrough and (not proxy_secret or resolve_cloud_token(pref_cloud_token)):
                try:
                    tok = ensure_cloud_token_for_proxy(proxy_base, pref_token=pref_cloud_token)
                    hdrs["X-Whisper-Cloud-Token"] = tok
                except Exception as e:
                    if not proxy_secret and not key:
                        raise RuntimeError(f"AI Modes: нет Cloud токена / ключа: {e}") from e
        elif key:
            hdrs["Authorization"] = f"Bearer {key}"
        elif not proxy_base:
            raise ValueError("Нужен GROQ_API_KEY для AI Modes без прокси.")
        return hdrs

    routes: list[tuple[str, str]] = []
    seen: set[str] = set()
    if proxy_enabled:
        for base in groq_proxy_url_candidates(pref_proxy_url):
            u = f"{base}/openai/v1/chat/completions"
            if u not in seen:
                seen.add(u)
                routes.append((u, base))
    direct = "https://api.groq.com/openai/v1/chat/completions"
    if key and direct not in seen:
        routes.append((direct, ""))
    if not routes:
        raise ValueError("AI Modes: включи Groq прокси или задай GROQ_API_KEY.")

    body = {
        "model": (model or os.environ.get("WHISPER_AI_MODE_MODEL") or DEFAULT_CHAT_MODEL).strip(),
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    def _post(
        url_: str,
        headers_: dict[str, str],
        model_id: str,
        to: tuple[float, float],
        auth_key: str | None = None,
    ) -> requests.Response:
        payload = dict(body)
        payload["model"] = model_id
        hdrs = dict(headers_)
        if auth_key:
            hdrs["Authorization"] = f"Bearer {auth_key}"

        def _call() -> requests.Response:
            return requests.post(url_, headers=hdrs, data=json.dumps(payload), timeout=to)

        if _is_layero_proxy(url_):
            return http_call_deadline(_call, deadline_sec=PROXY_CONNECT_DEADLINE_SEC)
        return _call()

    def _retryable(status: int, detail: str) -> bool:
        return status in (403, 404) or "model_not_found" in detail

    primary = str(body["model"])
    chain = [primary] + [m for m in FALLBACK_CHAT_MODELS if m != primary]
    conn_cap = min(float(timeout[0]), PROXY_CONNECT_DEADLINE_SEC)
    read_cap = min(float(timeout[1]), 25.0)
    route_timeout = (conn_cap, read_cap)

    last_detail = ""
    last_status = 0
    for url, proxy_base in routes:
        if proxy_base and is_proxy_unreachable(proxy_base):
            continue
        try:
            headers = _build_headers(proxy_base)
        except Exception as e:
            if log_error:
                log_error("ai_mode_headers_failed base=%r err=%s", proxy_base[:80], e)
            last_detail = str(e)[:400]
            if proxy_base:
                mark_proxy_unreachable(proxy_base)
            continue
        try:
            resp = _post(url, headers, chain[0], route_timeout)
            if is_proxy_cold_start_response(resp.status_code, resp.text or ""):
                time.sleep(2.0)
                resp = _post(url, headers, chain[0], route_timeout)
            use_proxy = "api.groq.com/openai" not in url
            if use_proxy and not passthrough and resp.status_code == 401:
                body_low = (resp.text or "").lower()
                if "invalid api key" in body_low or "invalid_api_key" in body_low:
                    for fk in [k for k in (resolve_groq_api_key(pref_api_key), groq_api_key_from_env()) if k]:
                        if log_error:
                            log_error("ai_mode_proxy_401_retry_with_client_key")
                        resp = _post(url, headers, chain[0], route_timeout, auth_key=fk)
                        if resp.status_code != 401:
                            break
            if resp.status_code >= 400:
                detail0 = (resp.text or "")[:400]
                if _retryable(resp.status_code, detail0):
                    for alt in chain[1:]:
                        if log_error:
                            log_error(
                                "ai_mode_model_retry %s -> %s status=%s",
                                primary,
                                alt,
                                resp.status_code,
                            )
                        resp = _post(url, headers, alt, route_timeout)
                        if resp.status_code < 400:
                            break
            if resp.status_code < 400:
                out = resp.json()
                try:
                    content = out["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    raise RuntimeError("ai_mode_bad_response") from e
                if proxy_base:
                    mark_proxy_reachable(proxy_base)
                return (content or "").strip()
            last_status = resp.status_code
            last_detail = (resp.text or "")[:400]
            if log_error:
                log_error("ai_mode_route status=%s url=%r", resp.status_code, url[:100])
            if resp.status_code not in (403, 502, 503, 504):
                break
        except requests.RequestException as e:
            last_detail = str(e)[:400]
            last_status = 0
            if proxy_base:
                mark_proxy_unreachable(proxy_base)
            if log_error:
                log_error("ai_mode_route_error url=%r err=%s", url[:100], e)
            continue

    if log_error:
        log_error("ai_mode_chat_http status=%s body=%r", last_status, last_detail)
    raise AiModeUnavailable(
        "ai_mode_proxy_unreachable: Groq прокси недоступен, оставляем сырой текст."
    )


def ai_mode_error_toast(err: Exception) -> str:
    s = str(err)
    if isinstance(err, AiModeUnavailable) or "ai_mode_proxy_unreachable" in s:
        return ""
    low = s.lower()
    if "layero_warming" in s or "запускается" in low:
        return ""
    if "<!doctype" in low:
        return ""
    if "HTTPSConnectionPool" in s or "ConnectTimeout" in s:
        return ""
    return s[:180]


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
    try:
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
    except AiModeProRequired:
        raise
    except Exception as e:
        if log_error:
            log_error("ai_mode_skipped_raw err=%s", e)
        return text


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
