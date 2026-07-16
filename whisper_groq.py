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
DEFAULT_GROQ_PROXY_URL = "https://whisper-groq-proxy-production.up.railway.app"

# Прокси (Railway/VPS), если api.groq.com с клиентской сети недоступен:
# WHISPER_GROQ_PROXY_URL=https://xxx.up.railway.app
# WHISPER_GROQ_PROXY_SECRET=… (если на прокси задан PROXY_SHARED_SECRET)

ALLOWED_TRANSCRIBE_MODES = frozenset(
    {"server", "groq", "server_then_groq", "groq_then_server", "auto_vram"}
)


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


def resolve_groq_proxy_enabled(pref_stored: bool | None = None) -> bool:
    for name in ("WHISPER_GROQ_PROXY_ENABLED", "GROQ_PROXY_ENABLED"):
        raw = (os.environ.get(name) or "").strip().lower()
        if raw in ("1", "true", "yes", "on"):
            return True
        if raw in ("0", "false", "no", "off"):
            return False
    if pref_stored is None:
        return True
    return bool(pref_stored)


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
    try:
        from whisper_file_log import user_data_dir

        return user_data_dir("WhisperHotkey") / "whisper_hotkey_prefs.json"
    except ImportError:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "whisper_hotkey_prefs.json"
        return Path(__file__).resolve().parent / "whisper_hotkey_prefs.json"


def load_hotkey_prefs() -> dict:
    p = hotkey_prefs_path()
    try:
        # utf-8-sig: PowerShell Set-Content -Encoding UTF8 часто пишет BOM → иначе JSON ломается.
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def save_hotkey_prefs(data: dict) -> None:
    p = hotkey_prefs_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def ensure_hotkey_default_prefs() -> dict:
    """Первый запуск Windows Hotkey: режим auto_vram (как удобный старт на Mac)."""
    data = load_hotkey_prefs()
    changed = False
    if not isinstance(data.get("transcribe_backend"), str) or not str(data.get("transcribe_backend")).strip():
        data["transcribe_backend"] = "auto_vram"
        changed = True
    if "model_key" not in data:
        data["model_key"] = "large-v3"
        changed = True
    if "notifications" not in data:
        data["notifications"] = True
        changed = True
    if "paste_mode" not in data:
        data["paste_mode"] = "auto"
        changed = True
    if changed:
        save_hotkey_prefs(data)
    return data


def read_hotkey_groq_proxy_url_pref() -> str | None:
    p = hotkey_prefs_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
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
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("groq_proxy_secret")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def read_hotkey_groq_proxy_enabled_pref() -> bool | None:
    p = hotkey_prefs_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("groq_proxy_enabled")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    return None


def read_hotkey_groq_api_key_pref() -> str | None:
    p = hotkey_prefs_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("groq_api_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def read_hotkey_transcribe_backend_pref() -> str | None:
    data = load_hotkey_prefs()
    v = data.get("transcribe_backend")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def read_hotkey_model_key_pref() -> str | None:
    data = load_hotkey_prefs()
    v = data.get("model_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def read_hotkey_auto_vram_margin_pref() -> float | None:
    data = load_hotkey_prefs()
    v = data.get("auto_vram_margin_gb")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def groq_is_configured() -> bool:
    if groq_api_key_from_env() or read_hotkey_groq_api_key_pref():
        return True
    proxy_enabled = read_hotkey_groq_proxy_enabled_pref()
    if proxy_enabled is False:
        return False
    return bool(resolve_groq_proxy_url(read_hotkey_groq_proxy_url_pref()))


def resolve_auto_vram_backend_order(
    model_key: str | None = None,
    *,
    margin_gb: float | None = None,
    log_info: Callable[..., None] | None = None,
) -> list[str]:
    """Перед каждой расшифровкой: достаточно свободной VRAM → локально, иначе Groq."""
    from whisper_models import SPEC_BY_KEY
    from whisper_system_profile import nvidia_free_vram_gb, nvidia_vram_snapshot

    key = (model_key or read_hotkey_model_key_pref() or "large-v3").strip() or "large-v3"
    spec = SPEC_BY_KEY.get(key) or SPEC_BY_KEY["large-v3"]
    margin = margin_gb
    if margin is None:
        margin = read_hotkey_auto_vram_margin_pref()
    if margin is None:
        raw = (os.environ.get("WHISPER_AUTO_VRAM_MARGIN_GB") or "0.8").strip()
        try:
            margin = float(raw)
        except ValueError:
            margin = 0.8
    needed = max(0.5, spec.min_vram_gb + margin)
    snap = nvidia_vram_snapshot()
    free = snap.get("vram_free_gb")
    if free is not None and float(free) >= needed:
        if log_info:
            log_info(
                "auto_vram local model=%s free=%.2f needed=%.2f",
                key,
                float(free),
                needed,
            )
        return ["server"]
    if groq_is_configured():
        if log_info:
            log_info(
                "auto_vram groq model=%s free=%s needed=%.2f",
                key,
                free,
                needed,
            )
        return ["groq"]
    if log_info:
        log_info(
            "auto_vram fallback_local model=%s free=%s needed=%.2f groq_unconfigured",
            key,
            free,
            needed,
        )
    return ["server"]


def resolve_transcribe_backend_mode(pref: str | None, *env_names: str) -> str:
    if isinstance(pref, str) and pref.strip() in ALLOWED_TRANSCRIBE_MODES:
        return pref.strip()
    for name in env_names:
        v = (os.environ.get(name) or "").strip().lower()
        if v in ALLOWED_TRANSCRIBE_MODES:
            return v
    return "auto_vram"


def transcribe_backend_order(mode: str) -> list[str]:
    if mode == "server":
        return ["server"]
    if mode == "groq":
        return ["groq"]
    if mode == "server_then_groq":
        return ["server", "groq"]
    return ["groq", "server"]


def hotkey_transcribe_backend_order(
    *,
    log_info: Callable[..., None] | None = None,
) -> list[str]:
    pref = read_hotkey_transcribe_backend_pref()
    mode = resolve_transcribe_backend_mode(
        pref,
        "WHISPER_TRANSCRIBE_BACKEND",
        "WHISPER_MAC_TRANSCRIBE_BACKEND",
    )
    if mode == "auto_vram":
        return resolve_auto_vram_backend_order(log_info=log_info)
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
    pref_proxy_enabled: bool | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    proxy_enabled = resolve_groq_proxy_enabled(pref_proxy_enabled)
    proxy_base = resolve_groq_proxy_url(pref_proxy_url) if proxy_enabled else ""
    url = (
        f"{proxy_base}/openai/v1/audio/transcriptions"
        if proxy_base
        else GROQ_TRANSCRIPTIONS_URL
    )
    use_proxy = bool(proxy_base)
    proxy_secret = resolve_groq_proxy_secret(pref_proxy_secret) if proxy_enabled else ""
    env_key = groq_api_key_from_env()
    pref_key = _clean_groq_key(pref_api_key)
    key = env_key or pref_key

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
    # Через прокси по умолчанию НЕ пробрасываем локальный ключ, чтобы серверный GROQ_API_KEY на прокси
    # работал даже если у клиента в .env/prefs лежит устаревший ключ.
    passthrough_auth = (os.environ.get("WHISPER_GROQ_PROXY_PASSTHROUGH_AUTH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if key and (not use_proxy or passthrough_auth):
        headers["Authorization"] = f"Bearer {key}"
    elif not use_proxy:
        raise ValueError("Внутренняя ошибка: нет ключа для прямого запроса к Groq.")

    prompt_str = (prompt or "").strip()

    def _post(model: str, *, auth_key: str | None) -> requests.Response:
        data: list[tuple[str, str]] = [
            ("model", model),
            ("response_format", "json"),
        ]
        if language:
            data.append(("language", language))
        if prompt_str:
            data.append(("prompt", prompt_str))
        req_headers = dict(headers)
        if auth_key:
            req_headers["Authorization"] = f"Bearer {auth_key}"
        else:
            req_headers.pop("Authorization", None)
        with open(wav_path, "rb") as wav:
            files = {"file": ("audio.wav", wav, "audio/wav")}
            return requests.post(
                url,
                headers=req_headers,
                data=dict(data),
                files=files,
                timeout=timeout,
            )

    auth_key = key if (not use_proxy or passthrough_auth) else None
    resp = _post(primary, auth_key=auth_key)
    # Для proxy-маршрута: если серверный ключ на прокси устарел, пробуем клиентские ключи.
    if use_proxy and not passthrough_auth and resp.status_code == 401:
        body = (resp.text or "").lower()
        if "invalid api key" in body or "invalid_api_key" in body:
            fallback_keys: list[str] = []
            if pref_key:
                fallback_keys.append(pref_key)
            if env_key and env_key != pref_key:
                fallback_keys.append(env_key)
            for fk in fallback_keys:
                if log_error:
                    log_error("groq_proxy_401_retry_with_client_key")
                resp = _post(primary, auth_key=fk)
                if resp.status_code != 401:
                    break
    if resp.status_code == 403 and primary == DEFAULT_GROQ_MODEL:
        if log_error:
            log_error("groq_transcribe_403_retry model=%s -> %s", primary, FALLBACK_GROQ_MODEL)
        resp = _post(FALLBACK_GROQ_MODEL, auth_key=auth_key)
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
