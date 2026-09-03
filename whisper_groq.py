"""Общий вызов Groq Speech-to-Text (OpenAI-совместимый) для Mac- и Windows-клиентов."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import requests

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_TRANSCRIBE_CHUNK_SEC = 110.0
GROQ_TRANSCRIBE_CHUNK_OVERLAP_SEC = 2.0
DEFAULT_GROQ_MODEL = "whisper-large-v3"
FALLBACK_GROQ_MODEL = "whisper-large-v3-turbo"
# Layero RF mirror is often a TCP/DNS blackhole from RF (Windows 10060 ~20–30s,
# requests timeout ignored). Railway origin is the working default.
LAYERO_GROQ_PROXY_URL = "https://whisper-groq-proxy.layero.app"
FALLBACK_GROQ_PROXY_URL = "https://whisper-groq-proxy-production.up.railway.app"
DEFAULT_GROQ_PROXY_URL = FALLBACK_GROQ_PROXY_URL

# Layero cold start returns 503 HTML «Запускается…» while RF mirror wakes up.
# Keep this short: a 45s retry chain after dictation feels like STT is frozen.
PROXY_COLD_START_DELAYS_SEC = (2.0, 4.0)
PROXY_CONNECT_DEADLINE_SEC = 3.0
_PROXY_DEAD_TTL_SEC = 300.0
_DEAD_PROXIES: dict[str, float] = {}
_LAST_GOOD_PROXY = ""

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
    cands = groq_proxy_url_candidates(pref_stored)
    if cands:
        return cands[0]
    return DEFAULT_GROQ_PROXY_URL.rstrip("/")


def _norm_proxy_base(base: str) -> str:
    return (base or "").strip().rstrip("/").lower()


def _is_layero_proxy(base: str) -> bool:
    return "layero.app" in _norm_proxy_base(base)


def reset_proxy_health_state() -> None:
    """Tests only."""
    global _LAST_GOOD_PROXY
    _DEAD_PROXIES.clear()
    _LAST_GOOD_PROXY = ""


def mark_proxy_unreachable(base: str) -> None:
    k = _norm_proxy_base(base)
    if k:
        _DEAD_PROXIES[k] = time.monotonic()


def mark_proxy_reachable(base: str) -> None:
    global _LAST_GOOD_PROXY
    b = (base or "").strip().rstrip("/")
    if not b:
        return
    _DEAD_PROXIES.pop(_norm_proxy_base(b), None)
    _LAST_GOOD_PROXY = b


def is_proxy_unreachable(base: str) -> bool:
    k = _norm_proxy_base(base)
    t = _DEAD_PROXIES.get(k)
    if t is None:
        return False
    if time.monotonic() - t > _PROXY_DEAD_TTL_SEC:
        _DEAD_PROXIES.pop(k, None)
        return False
    return True


def proxy_base_from_url(url: str) -> str:
    from urllib.parse import urlparse

    p = urlparse(url or "")
    if p.scheme and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    return (url or "").rstrip("/")


def groq_proxy_url_candidates(pref_stored: str | None = None) -> list[str]:
    """Railway first; Layero last (DNS/TCP blackhole). Skip hosts marked dead."""
    raw: list[str] = []
    seen: set[str] = set()
    for candidate in (
        _LAST_GOOD_PROXY,
        FALLBACK_GROQ_PROXY_URL,
        DEFAULT_GROQ_PROXY_URL,
        os.environ.get("WHISPER_GROQ_PROXY_URL"),
        os.environ.get("GROQ_PROXY_URL"),
        pref_stored,
        LAYERO_GROQ_PROXY_URL,
    ):
        if isinstance(candidate, str) and candidate.strip():
            u = candidate.strip().rstrip("/")
            if u not in seen:
                seen.add(u)
                raw.append(u)
    live = [u for u in raw if not is_proxy_unreachable(u) and not _is_layero_proxy(u)]
    layero_live = [u for u in raw if _is_layero_proxy(u) and not is_proxy_unreachable(u)]
    return live + layero_live


def http_call_deadline(fn: Callable[[], requests.Response], *, deadline_sec: float) -> requests.Response:
    """Windows DNS/TCP to dead hosts ignores requests timeout (WinError 10060 ~20–30s)."""
    import threading

    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["r"] = fn()
        except Exception as e:
            box["e"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(max(0.4, float(deadline_sec)))
    if t.is_alive():
        raise requests.ConnectTimeout(f"proxy_deadline_{deadline_sec:.1f}s")
    if "e" in box:
        raise box["e"]
    resp = box.get("r")
    if resp is None:
        raise requests.ConnectTimeout(f"proxy_deadline_{deadline_sec:.1f}s")
    return resp


def is_proxy_cold_start_response(status: int, body: str) -> bool:
    """Layero/Railway edge 503 HTML while serverless instance is starting."""
    if status not in (502, 503, 504):
        return False
    t = (body or "")[:900].lower()
    return "<!doctype html" in t or "запускается" in t or "starting" in t


def proxy_cold_start_delays() -> tuple[float, ...]:
    return PROXY_COLD_START_DELAYS_SEC


def probe_proxy_alive(
    base: str,
    *,
    deadline_sec: float | None = None,
    log_info: Callable[..., None] | None = None,
) -> bool:
    """Hard-capped reachability check. Windows often ignores requests' connect timeout."""
    b = (base or "").strip().rstrip("/")
    if not b:
        return False
    if is_proxy_unreachable(b):
        return False
    cap = float(deadline_sec if deadline_sec is not None else PROXY_CONNECT_DEADLINE_SEC)
    url = f"{b}/"

    def _call() -> requests.Response:
        return requests.get(url, timeout=(min(1.5, cap), min(2.0, cap)))

    try:
        http_call_deadline(_call, deadline_sec=cap)
        mark_proxy_reachable(b)
        if log_info:
            log_info("proxy_probe ok url=%r", url[:80])
        return True
    except requests.RequestException as e:
        mark_proxy_unreachable(b)
        if log_info:
            log_info("proxy_probe fail url=%r err=%s", url[:80], e)
        return False


def wake_groq_proxy_mirror(base: str, *, log_info: Callable[..., None] | None = None) -> None:
    """Warm Railway so the first dictation does not wait for a cold start."""
    b = (base or "").strip().rstrip("/")
    if not b or _is_layero_proxy(b) or is_proxy_unreachable(b):
        return
    probe_proxy_alive(b, deadline_sec=PROXY_CONNECT_DEADLINE_SEC, log_info=log_info)


def any_live_groq_proxy(pref_stored: str | None = None) -> bool:
    """True if at least one proxy candidate is not marked dead (and preferably probes OK)."""
    cands = [u for u in groq_proxy_url_candidates(pref_stored) if not _is_layero_proxy(u)]
    if not cands:
        cands = list(groq_proxy_url_candidates(pref_stored))
    for base in cands:
        if is_proxy_unreachable(base):
            continue
        if probe_proxy_alive(base):
            return True
    return False


def groq_rewrite_ready() -> bool:
    """AI polish needs a usable path — skip dead Cloud proxies instead of hanging 30–60s."""
    if groq_api_key_from_env() or read_hotkey_groq_api_key_pref():
        # Direct api.groq.com from RF is usually 403; still allow BYOK if proxy is on.
        proxy_on = resolve_groq_proxy_enabled(read_hotkey_groq_proxy_enabled_pref())
        if not proxy_on:
            return True
        return any_live_groq_proxy(read_hotkey_groq_proxy_url_pref())
    proxy_on = resolve_groq_proxy_enabled(read_hotkey_groq_proxy_enabled_pref())
    if proxy_on is False:
        return False
    return any_live_groq_proxy(read_hotkey_groq_proxy_url_pref())


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
    """UI prefs beat a stale .env WHISPER_GROQ_PROXY_ENABLED=0.

    Direct Groq from RF returns 403; the settings toggle must actually turn the proxy on.
    """
    if pref_stored is True:
        return True
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
    """Connect / read для requests; читает те же env, что и клиенты.

    Connect default 12s: Railway cold-start часто >4s; короткий connect
    ронял облако и кидал на медленный local GPU.
    """
    try:
        conn = float((os.environ.get("WHISPER_MAC_TRANSCRIBE_CONNECT_TIMEOUT") or "").strip() or "12")
    except ValueError:
        conn = 12.0
    conn = max(4.0, min(45.0, conn))
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
    """Windows Hotkey: облако первым (секунды, как Cursor), GPU — запасной путь."""
    data = load_hotkey_prefs()
    changed = False
    if not isinstance(data.get("transcribe_backend"), str) or not str(data.get("transcribe_backend")).strip():
        data["transcribe_backend"] = "groq_then_server"
        changed = True
    # One-shot: старый «только GPU» + Cloud уже настроен → иначе диктовка минутами/часами.
    if not data.get("dictation_speed_v1"):
        backend = str(data.get("transcribe_backend") or "").strip()
        cloud_ready = bool(
            (isinstance(data.get("cloud_token"), str) and data["cloud_token"].startswith("wsk_"))
            or (isinstance(data.get("groq_api_key"), str) and data["groq_api_key"].strip())
            or groq_api_key_from_env()
            or data.get("groq_proxy_enabled") is not False
        )
        if cloud_ready and backend in ("server", "auto_vram", "server_then_groq"):
            data["transcribe_backend"] = "groq_then_server"
            changed = True
        data["dictation_speed_v1"] = True
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
    if not isinstance(data.get("ai_mode"), str) or not str(data.get("ai_mode")).strip():
        data["ai_mode"] = "auto"
        changed = True
    stored_proxy = str(data.get("groq_proxy_url") or "").strip()
    if (not stored_proxy) or _is_layero_proxy(stored_proxy):
        data["groq_proxy_url"] = DEFAULT_GROQ_PROXY_URL
        data["groq_proxy_enabled"] = True
        changed = True
    if changed:
        save_hotkey_prefs(data)
    return data


class CloudQuotaExceeded(RuntimeError):
    """HTTP 402: free Cloud minutes exhausted."""

    def __init__(self, message: str, *, remaining_seconds: float = 0.0, body: dict | None = None):
        super().__init__(message)
        self.remaining_seconds = float(remaining_seconds)
        self.body = body or {}


def _uuid4() -> str:
    import uuid

    return str(uuid.uuid4())


def read_hotkey_cloud_token_pref() -> str | None:
    data = load_hotkey_prefs()
    v = data.get("cloud_token")
    if isinstance(v, str) and v.strip().startswith("wsk_"):
        return v.strip()
    return None


def read_hotkey_cloud_device_id_pref() -> str | None:
    data = load_hotkey_prefs()
    v = data.get("cloud_device_id")
    if isinstance(v, str) and len(v.strip()) >= 8:
        return v.strip()
    return None


def resolve_cloud_token(pref_stored: str | None = None) -> str:
    for candidate in (
        os.environ.get("WHISPER_CLOUD_TOKEN"),
        os.environ.get("WHISPER_GROQ_CLOUD_TOKEN"),
        pref_stored,
        read_hotkey_cloud_token_pref(),
    ):
        if isinstance(candidate, str) and candidate.strip().startswith("wsk_"):
            return candidate.strip()
    return ""


def ensure_cloud_device_id(*, pref_get: dict | None = None, pref_save: Callable[[dict], None] | None = None) -> str:
    """Stable anonymous device id in hotkey prefs (or provided dict)."""
    if pref_get is not None:
        existing = pref_get.get("cloud_device_id")
        if isinstance(existing, str) and len(existing.strip()) >= 8:
            return existing.strip()
        did = _uuid4()
        pref_get["cloud_device_id"] = did
        if pref_save:
            pref_save(pref_get)
        return did
    existing = read_hotkey_cloud_device_id_pref()
    if existing:
        return existing
    did = _uuid4()
    data = load_hotkey_prefs()
    data["cloud_device_id"] = did
    save_hotkey_prefs(data)
    return did


def register_cloud_device(
    proxy_base: str,
    *,
    device_id: str | None = None,
    timeout: float = 8.0,
) -> dict:
    """POST /v1/devices/register → {token, plan, remaining_…}."""
    base = (proxy_base or DEFAULT_GROQ_PROXY_URL).rstrip("/")
    did = (device_id or ensure_cloud_device_id()).strip()

    def _call() -> requests.Response:
        return requests.post(
            f"{base}/v1/devices/register",
            json={"device_id": did},
            headers={"Accept": "application/json", "User-Agent": "WhisperClient/1.0"},
            timeout=timeout,
        )

    if _is_layero_proxy(base):
        r = http_call_deadline(_call, deadline_sec=min(float(timeout), PROXY_CONNECT_DEADLINE_SEC))
    else:
        r = _call()
    if r.status_code >= 400:
        raise RuntimeError(f"cloud_register_http_{r.status_code}:{(r.text or '')[:300]}")
    out = r.json()
    if not isinstance(out, dict) or not str(out.get("token", "")).startswith("wsk_"):
        raise RuntimeError("cloud_register_bad_response")
    return out


def fetch_cloud_me(proxy_base: str, token: str, *, timeout: float = 20.0) -> dict:
    base = (proxy_base or DEFAULT_GROQ_PROXY_URL).rstrip("/")
    r = requests.get(
        f"{base}/v1/me",
        headers={
            "Accept": "application/json",
            "X-Whisper-Cloud-Token": token,
            "User-Agent": "WhisperClient/1.0",
        },
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"cloud_me_http_{r.status_code}:{(r.text or '')[:300]}")
    out = r.json()
    if not isinstance(out, dict):
        raise RuntimeError("cloud_me_bad_response")
    return out


def create_cloud_checkout(proxy_base: str, token: str, *, timeout: float = 30.0) -> dict:
    base = (proxy_base or DEFAULT_GROQ_PROXY_URL).rstrip("/")
    r = requests.post(
        f"{base}/v1/checkout",
        headers={
            "Accept": "application/json",
            "X-Whisper-Cloud-Token": token,
            "User-Agent": "WhisperClient/1.0",
        },
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"cloud_checkout_http_{r.status_code}:{(r.text or '')[:400]}")
    out = r.json()
    if not isinstance(out, dict):
        raise RuntimeError("cloud_checkout_bad_response")
    return out


def ensure_cloud_token_for_proxy(
    proxy_base: str,
    *,
    pref_token: str | None = None,
    device_id: str | None = None,
    persist_hotkey: bool = True,
    on_registered: Callable[[str, dict], None] | None = None,
) -> str:
    """Return wsk_…; register + persist if missing."""
    tok = resolve_cloud_token(pref_token)
    if tok:
        return tok
    did = (device_id or "").strip() or ensure_cloud_device_id()
    snap = register_cloud_device(proxy_base, device_id=did)
    token = str(snap["token"])
    if persist_hotkey:
        data = load_hotkey_prefs()
        data["cloud_token"] = token
        data["cloud_device_id"] = str(snap.get("device_id") or did)
        save_hotkey_prefs(data)
    if on_registered:
        on_registered(token, snap)
    return token


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
    """Диктовка: при Cloud/Groq — облако первым (секунды), GPU только запасной.

    Раньше при свободной VRAM брали только local large-v3 — на длинных кусках
    это минуты; Cursor-like UX = groq → server.
    """
    from whisper_models import SPEC_BY_KEY
    from whisper_system_profile import nvidia_vram_snapshot

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
    local_ok = free is not None and float(free) >= needed
    if groq_is_configured():
        if log_info:
            log_info(
                "auto_vram groq_then_local model=%s free=%s needed=%.2f local_ok=%s",
                key,
                free,
                needed,
                local_ok,
            )
        return ["groq", "server"] if local_ok else ["groq"]
    if local_ok:
        if log_info:
            log_info(
                "auto_vram local model=%s free=%.2f needed=%.2f",
                key,
                float(free),
                needed,
            )
        return ["server"]
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
    return "groq_then_server"


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
    pref_cloud_token: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    try:
        import soundfile as sf

        info = sf.info(wav_path)
        dur = float(info.duration)
        chunk_sec = float(
            (os.environ.get("WHISPER_GROQ_CHUNK_SEC") or "").strip() or GROQ_TRANSCRIBE_CHUNK_SEC
        )
        chunk_sec = max(30.0, chunk_sec)
        if dur > chunk_sec + 5.0:
            overlap = GROQ_TRANSCRIBE_CHUNK_OVERLAP_SEC
            total_frames = int(info.frames)
            sr = int(info.samplerate)
            chunk_frames = int(chunk_sec * sr)
            overlap_frames = int(overlap * sr)
            texts: list[str] = []
            start = 0
            while start < total_frames:
                end = min(start + chunk_frames, total_frames)
                data, _ = sf.read(wav_path, start=start, stop=end, always_2d=False)
                fd, tmp = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                try:
                    sf.write(tmp, data, sr)
                    part = post_groq_audio_transcription(
                        tmp,
                        language=language,
                        timeout=timeout,
                        log_error=log_error,
                        pref_api_key=pref_api_key,
                        pref_proxy_url=pref_proxy_url,
                        pref_proxy_secret=pref_proxy_secret,
                        pref_proxy_enabled=pref_proxy_enabled,
                        pref_cloud_token=pref_cloud_token,
                        prompt=prompt,
                    )
                    t = (part.get("text") or "").strip()
                    if t:
                        texts.append(t)
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                if end >= total_frames:
                    break
                start = max(start + 1, end - overlap_frames)
            if log_error:
                log_error("groq_transcribe_chunked parts=%d dur=%.1f", len(texts), dur)
            return {"text": " ".join(texts)}
    except Exception as e:
        if log_error:
            log_error("groq_chunk_probe_failed err=%s", e)

    proxy_enabled = resolve_groq_proxy_enabled(pref_proxy_enabled)
    proxy_secret = resolve_groq_proxy_secret(pref_proxy_secret) if proxy_enabled else ""
    env_key = groq_api_key_from_env()
    pref_key = _clean_groq_key(pref_api_key)
    key = env_key or pref_key
    passthrough_auth = (os.environ.get("WHISPER_GROQ_PROXY_PASSTHROUGH_AUTH") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if not proxy_enabled and not key:
        raise ValueError(
            "Нет ключа Groq: GROQ_API_KEY в .env или ключ в настройках приложения "
            "(Mac: меню 🎤; Windows: трей → Groq API ключ). "
            "Либо задай WHISPER_GROQ_PROXY_URL на Railway-прокси (см. groq_proxy/README.md).",
        )

    primary = groq_transcription_model_primary()
    from whisper_quality import merge_initial_prompt

    prompt_str = merge_initial_prompt(prompt)

    def _build_route_headers(proxy_base: str) -> dict[str, str]:
        hdrs: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "WhisperClient/1.0 (Whisper Mac & Windows hotkey)",
        }
        if proxy_secret:
            hdrs["X-Whisper-Groq-Proxy-Secret"] = proxy_secret
        if proxy_base:
            if key and passthrough_auth:
                hdrs["Authorization"] = f"Bearer {key}"
            elif not passthrough_auth and (not proxy_secret or resolve_cloud_token(pref_cloud_token)):
                try:
                    tok = ensure_cloud_token_for_proxy(proxy_base, pref_token=pref_cloud_token)
                    hdrs["X-Whisper-Cloud-Token"] = tok
                except Exception as e:
                    if not proxy_secret:
                        raise RuntimeError(
                            f"Не удалось зарегистрировать Whisper Cloud: {e}. "
                            "Проверь интернет или вставь токен wsk_… в настройках Cloud."
                        ) from e
                    if log_error:
                        log_error("cloud_register_skipped_using_proxy_secret err=%s", e)
        elif key:
            hdrs["Authorization"] = f"Bearer {key}"
        return hdrs

    routes: list[tuple[str, dict[str, str], str | None]] = []
    seen_urls: set[str] = set()
    if proxy_enabled:
        # Prefer working Railway/VPS; Layero often blackholes from RF — try after BYOK.
        non_layero = [b for b in groq_proxy_url_candidates(pref_proxy_url) if not _is_layero_proxy(b)]
        for base in non_layero:
            route_url = f"{base}/openai/v1/audio/transcriptions"
            if route_url in seen_urls:
                continue
            seen_urls.add(route_url)
            auth_key = key if passthrough_auth else None
            routes.append((route_url, _build_route_headers(base), auth_key))
    if key and GROQ_TRANSCRIPTIONS_URL not in seen_urls:
        routes.append((GROQ_TRANSCRIPTIONS_URL, _build_route_headers(""), key))
        seen_urls.add(GROQ_TRANSCRIPTIONS_URL)
    if proxy_enabled:
        for base in groq_proxy_url_candidates(pref_proxy_url):
            if not _is_layero_proxy(base):
                continue
            route_url = f"{base}/openai/v1/audio/transcriptions"
            if route_url in seen_urls:
                continue
            seen_urls.add(route_url)
            auth_key = key if passthrough_auth else None
            routes.append((route_url, _build_route_headers(base), auth_key))

    if not routes:
        raise ValueError(
            "Groq недоступен: включи прокси в меню Groq API или задай GROQ_API_KEY.",
        )

    def _post(
        model: str,
        *,
        url: str,
        req_headers: dict[str, str],
        auth_key: str | None,
        req_timeout: tuple[float, float] | None = None,
    ) -> requests.Response:
        data: list[tuple[str, str]] = [
            ("model", model),
            ("response_format", "json"),
        ]
        if language:
            data.append(("language", language))
        if prompt_str:
            data.append(("prompt", prompt_str))
        hdrs = dict(req_headers)
        if auth_key:
            hdrs["Authorization"] = f"Bearer {auth_key}"
        else:
            hdrs.pop("Authorization", None)
        def _call() -> requests.Response:
            with open(wav_path, "rb") as wav:
                files = {"file": ("audio.wav", wav, "audio/wav")}
                return requests.post(
                    url,
                    headers=hdrs,
                    data=dict(data),
                    files=files,
                    timeout=req_timeout or timeout,
                )

        if _is_layero_proxy(url):
            return http_call_deadline(_call, deadline_sec=PROXY_CONNECT_DEADLINE_SEC)
        return _call()

    def _raise_quota(resp: requests.Response) -> None:
        detail = (resp.text or "")[:500]
        remaining = 0.0
        body: dict[str, Any] = {}
        try:
            body = resp.json()
            if isinstance(body, dict):
                remaining = float(body.get("remaining_seconds") or 0)
        except Exception:
            body = {}
        if log_error:
            log_error("cloud_quota_exceeded remaining=%s body=%r", remaining, detail)
        raise CloudQuotaExceeded(
            "Минуты Whisper Cloud на этот месяц закончились. "
            "Оформи Pro в настройках Cloud или используй локальный GPU / свой ключ Groq.",
            remaining_seconds=remaining,
            body=body if isinstance(body, dict) else {},
        )

    def _attempt(
        url: str,
        req_headers: dict[str, str],
        auth_key: str | None,
        req_timeout: tuple[float, float],
    ) -> requests.Response:
        use_proxy = GROQ_TRANSCRIPTIONS_URL not in url
        resp = _post(primary, url=url, req_headers=req_headers, auth_key=auth_key, req_timeout=req_timeout)
        if use_proxy and not passthrough_auth and resp.status_code == 401:
            body = (resp.text or "").lower()
            if "invalid api key" in body or "invalid_api_key" in body:
                for fk in [k for k in (pref_key, env_key) if k]:
                    if log_error:
                        log_error("groq_proxy_401_retry_with_client_key")
                    resp = _post(primary, url=url, req_headers=req_headers, auth_key=fk, req_timeout=req_timeout)
                    if resp.status_code != 401:
                        break
        if resp.status_code == 403 and primary == DEFAULT_GROQ_MODEL:
            if log_error:
                log_error("groq_transcribe_403_retry model=%s -> %s", primary, FALLBACK_GROQ_MODEL)
            resp = _post(
                FALLBACK_GROQ_MODEL,
                url=url,
                req_headers=req_headers,
                auth_key=auth_key,
                req_timeout=req_timeout,
            )
        if resp.status_code == 402:
            _raise_quota(resp)
        return resp

    last_detail = ""
    last_status = 0
    for url, req_headers, auth_key in routes:
        if is_proxy_unreachable(proxy_base_from_url(url)):
            continue
        # Layero: hard-cap (Windows blackhole). Railway/direct: full STT timeout.
        if _is_layero_proxy(url):
            route_timeout = (
                min(float(timeout[0]), PROXY_CONNECT_DEADLINE_SEC + 1.0),
                min(float(timeout[1]), 20.0),
            )
        else:
            route_timeout = (float(timeout[0]), float(timeout[1]))
        try:
            resp: requests.Response | None = None
            for cold_try, delay in enumerate((0.0, *proxy_cold_start_delays())):
                if delay > 0:
                    if log_error:
                        log_error("groq_cold_start_retry url=%r wait=%.0fs", url[:80], delay)
                    time.sleep(delay)
                resp = _attempt(url, req_headers, auth_key, route_timeout)
                if resp.status_code < 400:
                    break
                if is_proxy_cold_start_response(resp.status_code, resp.text or ""):
                    if cold_try < len(proxy_cold_start_delays()):
                        continue
                break
            assert resp is not None
        except CloudQuotaExceeded:
            raise
        except requests.RequestException as e:
            last_detail = str(e)[:400]
            last_status = 0
            mark_proxy_unreachable(proxy_base_from_url(url))
            if log_error:
                log_error("groq_transcribe_route_error url=%r err=%s", url[:100], e)
            continue
        if resp.status_code < 400:
            try:
                out = resp.json()
            except ValueError as e:
                raise ValueError("Ответ Groq не JSON") from e
            if not isinstance(out, dict):
                raise ValueError("Ответ Groq: не объект JSON")
            mark_proxy_reachable(proxy_base_from_url(url))
            return out
        last_status = resp.status_code
        last_detail = (resp.text or "")[:400]
        if log_error:
            log_error(
                "groq_transcribe_route status=%s url=%r body_prefix=%r",
                resp.status_code,
                url[:100],
                last_detail,
            )
        if resp.status_code not in (403, 502, 503, 504):
            break

    hint = ""
    if last_status == 403:
        hint = (
            " Из РФ нужен прокси (меню Groq API → включить). "
            "Модель: GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo."
        )
    raise RuntimeError(f"groq_http_{last_status}:{last_detail}{hint}")
