"""Общий вызов Groq Speech-to-Text (OpenAI-совместимый) для Mac- и Windows-клиентов."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import requests

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_GROQ_MODEL = "whisper-large-v3"
FALLBACK_GROQ_MODEL = "whisper-large-v3-turbo"

# Прокси (Railway/VPS), если api.groq.com с клиентской сети недоступен:
# WHISPER_GROQ_PROXY_URL=https://xxx.up.railway.app
# WHISPER_GROQ_PROXY_SECRET=… (если на прокси задан PROXY_SHARED_SECRET)

ALLOWED_TRANSCRIBE_MODES = frozenset({"server", "groq", "server_then_groq", "groq_then_server"})


def _clean_groq_key(raw: str | None) -> str | None:
    if raw is None or not isinstance(raw, str):
        return None
    k = raw.strip()
    if k.startswith("\ufeff"):
        k = k.lstrip("\ufeff")
    k = k.strip()
    return k or None


def groq_api_key_from_env() -> str | None:
    return _clean_groq_key(
        os.environ.get("GROQ_API_KEY") or os.environ.get("WHISPER_GROQ_API_KEY") or "",
    )


def resolve_groq_proxy_url(pref_stored: str | None = None) -> str:
    for candidate in (
        os.environ.get("WHISPER_GROQ_PROXY_URL"),
        os.environ.get("GROQ_PROXY_URL"),
        pref_stored,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().rstrip("/")
    return ""


def resolve_groq_proxy_secret(pref_stored: str | None = None) -> str:
    for candidate in (
        os.environ.get("WHISPER_GROQ_PROXY_SECRET"),
        os.environ.get("GROQ_PROXY_SECRET"),
        pref_stored,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def resolve_groq_api_key(pref_stored: str | None = None) -> str | None:
    """Сначала переменные окружения, иначе ключ из настроек (JSON prefs)."""
    k = groq_api_key_from_env()
    if k:
        return k
    return _clean_groq_key(pref_stored)


def normalize_groq_api_key() -> str | None:
    """Только env (обратная совместимость)."""
    return groq_api_key_from_env()


def groq_transcription_model_primary() -> str:
    return (os.environ.get("GROQ_TRANSCRIPTION_MODEL") or DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL


def groq_http_timeout_tuple(*, read_cap: float = 600.0) -> tuple[float, float]:
    """Connect / read для requests; читает те же env, что и клиенты."""
    try:
        conn = float((os.environ.get("WHISPER_MAC_TRANSCRIBE_CONNECT_TIMEOUT") or "").strip() or "60")
    except ValueError:
        conn = 60.0
    conn = max(10.0, min(120.0, conn))
    hotkey = (os.environ.get("WHISPER_HOTKEY_TRANSCRIBE_TIMEOUT") or "").strip()
    mac = (os.environ.get("WHISPER_MAC_TRANSCRIBE_TIMEOUT") or "").strip()
    raw = hotkey or mac or "900"
    try:
        read = float(raw)
    except ValueError:
        read = 900.0
    read = max(60.0, min(read_cap, read))
    return conn, read


def load_whisper_dotenv_files() -> list[Path]:
    """Windows hotkey / CLI: .env рядом с exe или скриптом, родители, %APPDATA%\\WhisperClient\\.env."""
    seen: set[Path] = set()
    to_read: list[Path] = []

    def _queue(p: Path) -> None:
        if not p.is_file():
            return
        try:
            k = p.resolve()
        except OSError:
            k = p
        if k in seen:
            return
        seen.add(k)
        to_read.append(p)

    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    _queue(root / ".env")
    cur = root
    for _ in range(16):
        cur = cur.parent
        if cur == cur.parent:
            break
        _queue(cur / ".env")
    ad = os.environ.get("APPDATA", "")
    if ad:
        _queue(Path(ad) / "WhisperClient" / ".env")

    loaded: list[Path] = []
    for p in to_read:
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError:
            continue
        loaded.append(p)
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1].strip()
            if k and v:
                os.environ[k] = v
    return loaded


def hotkey_prefs_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "whisper_hotkey_prefs.json"
    return Path(__file__).resolve().parent / "whisper_hotkey_prefs.json"


def read_hotkey_groq_proxy_url_pref() -> str | None:
    p = hotkey_prefs_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("groq_proxy_url")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def read_hotkey_groq_proxy_secret_pref() -> str | None:
    p = hotkey_prefs_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("groq_proxy_secret")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def read_hotkey_groq_api_key_pref() -> str | None:
    p = hotkey_prefs_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("groq_api_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def read_hotkey_transcribe_backend_pref() -> str | None:
    p = hotkey_prefs_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("transcribe_backend")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def resolve_transcribe_backend_mode(pref: str | None, *env_names: str) -> str:
    if isinstance(pref, str) and pref.strip() in ALLOWED_TRANSCRIBE_MODES:
        return pref.strip()
    for name in env_names:
        v = (os.environ.get(name) or "").strip().lower()
        if v in ALLOWED_TRANSCRIBE_MODES:
            return v
    return "server"


def transcribe_backend_order(mode: str) -> list[str]:
    if mode == "server":
        return ["server"]
    if mode == "groq":
        return ["groq"]
    if mode == "server_then_groq":
        return ["server", "groq"]
    return ["groq", "server"]


def hotkey_transcribe_backend_order() -> list[str]:
    pref = read_hotkey_transcribe_backend_pref()
    mode = resolve_transcribe_backend_mode(
        pref,
        "WHISPER_TRANSCRIBE_BACKEND",
        "WHISPER_MAC_TRANSCRIBE_BACKEND",
    )
    return transcribe_backend_order(mode)


def post_groq_audio_transcription(
    wav_path: str,
    *,
    language: str | None = None,
    timeout: tuple[float, float],
    log_error: Callable[..., None] | None = None,
    pref_api_key: str | None = None,
    pref_proxy_url: str | None = None,
    pref_proxy_secret: str | None = None,
) -> dict[str, Any]:
    proxy_base = resolve_groq_proxy_url(pref_proxy_url)
    url = (
        f"{proxy_base}/openai/v1/audio/transcriptions"
        if proxy_base
        else GROQ_TRANSCRIPTIONS_URL
    )
    use_proxy = bool(proxy_base)
    proxy_secret = resolve_groq_proxy_secret(pref_proxy_secret)
    key = resolve_groq_api_key(pref_api_key)

    if not use_proxy and not key:
        raise ValueError(
            "Нет ключа Groq: GROQ_API_KEY в .env или ключ в настройках приложения "
            "(Mac: меню 🎤; Windows: трей → Groq API ключ). "
            "Либо задай WHISPER_GROQ_PROXY_URL на Railway-прокси (см. groq_proxy/README.md).",
        )

    primary = groq_transcription_model_primary()
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": "WhisperClient/1.0 (Whisper Mac & Windows hotkey)",
    }
    if proxy_secret:
        headers["X-Whisper-Groq-Proxy-Secret"] = proxy_secret
    if key:
        headers["Authorization"] = f"Bearer {key}"
    elif not use_proxy:
        raise ValueError("Внутренняя ошибка: нет ключа для прямого запроса к Groq.")

    def _post(model: str) -> requests.Response:
        data: list[tuple[str, str]] = [
            ("model", model),
            ("response_format", "json"),
        ]
        if language:
            data.append(("language", language))
        with open(wav_path, "rb") as wav:
            files = {"file": ("audio.wav", wav, "audio/wav")}
            return requests.post(
                url,
                headers=headers,
                data=dict(data),
                files=files,
                timeout=timeout,
            )

    resp = _post(primary)
    if resp.status_code == 403 and primary == DEFAULT_GROQ_MODEL:
        if log_error:
            log_error("groq_transcribe_403_retry model=%s -> %s", primary, FALLBACK_GROQ_MODEL)
        resp = _post(FALLBACK_GROQ_MODEL)
    if resp.status_code >= 400:
        detail = (resp.text or "")[:400]
        if log_error:
            log_error("groq_transcribe_http status=%s body_prefix=%r", resp.status_code, detail)
        hint = ""
        if resp.status_code == 403:
            hint = (
                " Новый ключ: console.groq.com; из РФ часто нужен прокси: WHISPER_GROQ_PROXY_URL (groq_proxy на Railway). "
                "Модель: GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo."
            )
        raise RuntimeError(f"groq_http_{resp.status_code}:{detail}{hint}")
    try:
        out = resp.json()
    except ValueError as e:
        raise ValueError("Ответ Groq не JSON") from e
    if not isinstance(out, dict):
        raise ValueError("Ответ Groq: не объект JSON")
    return out
