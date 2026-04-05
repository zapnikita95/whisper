"""Проверка обновлений через GitHub Releases (без лишних зависимостей).

Сначала пробуем REST API (нужен для полного JSON с assets). Без токена лимит ~60 запросов/час
на IP (общий для всех за этим NAT/VPN) — часто даёт 403.

Если API недоступен, используем обход: HTTP GET на https://github.com/<repo>/releases/latest
(не api.github.com) — редирект на /releases/tag/vX.Y.Z, откуда собираем прямую ссылку на DMG:
/releases/download/<tag>/WhisperClient-<ver>.dmg — это не расходует квоту API.

Опционально: WHISPER_GITHUB_TOKEN / GITHUB_TOKEN — 5000 запросов/час к API.
Кэш на диске: 1 ч авто, 5 мин ручная проверка.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

_LOG = logging.getLogger("whisper_update_check")

# TTL кэша: 1 час для автоматических проверок, 5 мин для ручных
_CACHE_TTL_AUTO = 3600.0
_CACHE_TTL_MANUAL = 300.0


def releases_repo() -> str:
    return (os.environ.get("WHISPER_RELEASES_REPO") or "zapnikita95/whisper").strip()


def skip_update_check() -> bool:
    return os.environ.get("WHISPER_SKIP_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes")


def _cache_path() -> str:
    base = os.path.expanduser("~/Library/Caches/WhisperClient")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "update_check_cache.json")


def _read_cache() -> dict[str, Any] | None:
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(release: dict[str, Any]) -> None:
    try:
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "release": release}, f)
    except Exception:
        pass


def _version_tuple(tag: str) -> tuple[int, ...]:
    s = tag.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in s.split("."):
        m = re.match(r"^(\d+)", chunk)
        parts.append(int(m.group(1)) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def is_remote_newer(remote_tag: str, current_version: str) -> bool:
    return _version_tuple(remote_tag) > _version_tuple(current_version)


def _github_ua() -> str:
    return (
        "WhisperClient/1.0 (+https://github.com/zapnikita95/whisper; update check)"
    )


def _http_fetch(url: str, *, timeout: float = 25) -> tuple[str, bytes]:
    """GET с редиректами: сначала requests (свои CA), иначе urllib."""
    headers = {"User-Agent": _github_ua(), "Accept": "*/*"}
    try:
        import requests

        r = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
        r.raise_for_status()
        return str(r.url), r.content
    except Exception as e:
        _LOG.debug("http_fetch_requests url=%s err=%s", url, e)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.geturl(), resp.read()


def _synthetic_release_from_tag_url(tag: str, final_url_hint: str) -> dict[str, Any]:
    repo = releases_repo()
    tag = tag.strip()
    ver = tag[1:] if tag.lower().startswith("v") and len(tag) > 1 else tag
    dmg_name = f"WhisperClient-{ver}.dmg"
    dl = f"https://github.com/{repo}/releases/download/{tag}/{dmg_name}"
    return {
        "tag_name": tag,
        "html_url": final_url_hint
        if "/releases/tag/" in final_url_hint
        else f"https://github.com/{repo}/releases/tag/{tag}",
        "assets": [{"name": dmg_name, "browser_download_url": dl}],
        "_whisper_synthetic": True,
    }


def _fetch_latest_via_web_redirect() -> dict[str, Any] | None:
    """Без api.github.com: редирект /releases/latest → /releases/tag/vX.Y.Z, затем прямая ссылка на DMG."""
    repo = releases_repo()
    url = f"https://github.com/{repo}/releases/latest"
    try:
        final, _body = _http_fetch(url, timeout=25)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as e:
        _LOG.warning("github_web_redirect_failed %s", e)
        return None
    m = re.search(r"/releases/tag/([^/?#]+)", final)
    if not m:
        _LOG.warning("github_web_redirect_no_tag url=%r", final)
        return None
    tag = m.group(1).strip()
    syn = _synthetic_release_from_tag_url(tag, final)
    _LOG.info("github_release_synthetic_redirect tag=%s", tag)
    return syn


def _fetch_latest_via_releases_atom() -> dict[str, Any] | None:
    """Atom-лента релизов — без REST API и без лимита api.github.com."""
    repo = releases_repo()
    url = f"https://github.com/{repo}/releases.atom"
    try:
        _final, raw = _http_fetch(url, timeout=25)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as e:
        _LOG.warning("github_atom_failed %s", e)
        return None
    text = raw.decode("utf-8", errors="replace")
    if "<entry>" not in text:
        _LOG.warning("github_atom_no_entries")
        return None
    entry = text.split("<entry>", 1)[1].split("</entry>", 1)[0]
    m = re.search(
        r'href="(https://github\.com/[^"]+/releases/tag/[^"]+)"',
        entry,
    )
    if not m:
        m = re.search(r"/releases/tag/([^\"<\s]+)", entry)
        if not m:
            _LOG.warning("github_atom_no_tag_in_first_entry")
            return None
        tag = m.group(1).strip()
        page = f"https://github.com/{repo}/releases/tag/{tag}"
    else:
        page = m.group(1).strip()
        mt = re.search(r"/releases/tag/([^/?#]+)", page)
        if not mt:
            return None
        tag = mt.group(1).strip()
    syn = _synthetic_release_from_tag_url(tag, page)
    _LOG.info("github_release_synthetic_atom tag=%s", tag)
    return syn


def _try_github_release_fallbacks() -> dict[str, Any] | None:
    fb = _fetch_latest_via_web_redirect()
    if fb:
        return fb
    return _fetch_latest_via_releases_atom()


def fetch_latest_release(*, force: bool = False) -> dict[str, Any] | None:
    """Получить последний релиз: без токена — сначала web (редирект/atom), затем API; с токеном — API, затем web."""
    if skip_update_check():
        return None

    ttl = _CACHE_TTL_MANUAL if force else _CACHE_TTL_AUTO
    if not force:
        cached = _read_cache()
        if cached and isinstance(cached, dict):
            age = time.time() - float(cached.get("ts", 0))
            if age < ttl:
                return cached.get("release")

    token = (
        os.environ.get("WHISPER_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    ).strip()
    has_token = bool(token)

    if not has_token:
        fb = _try_github_release_fallbacks()
        if fb:
            _write_cache(fb)
            return fb

    url = f"https://api.github.com/repos/{releases_repo()}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _github_ua(),
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if has_token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode())
            _write_cache(release)
            return release
    except urllib.error.HTTPError as e:
        has_token = bool(
            (os.environ.get("WHISPER_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
        )
        if e.code == 403:
            _LOG.warning(
                "github_releases_http_403 (rate limit API; токен в env: %s) — пробуем web-редирект",
                "да" if has_token else "нет",
            )
            fb = _try_github_release_fallbacks()
            if fb:
                _write_cache(fb)
                return fb
            cached = _read_cache()
            if cached and isinstance(cached, dict) and cached.get("release"):
                return cached["release"]
        elif e.code == 404:
            _LOG.warning(
                "github_releases_http_404 (нет latest или приватный репо без токена; токен: %s)",
                "да" if has_token else "нет",
            )
        else:
            _LOG.warning("github_releases_http_%s", e.code)
        fb = _try_github_release_fallbacks()
        if fb:
            _write_cache(fb)
            return fb
        return None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as e:
        _LOG.warning("github_releases_request_error %s — пробуем web-редирект/atom", e)
        fb = _try_github_release_fallbacks()
        if fb:
            _write_cache(fb)
            return fb
        cached = _read_cache()
        if cached and isinstance(cached, dict) and cached.get("release"):
            return cached["release"]
        return None


def pick_asset_url(release: dict[str, Any], *, suffix: str, contains: str | None = None) -> tuple[str, str] | None:
    """Возвращает (имя, url) asset: точное имя из WHISPER_UPDATE_ASSET_NAME, иначе .dmg с фильтром contains, иначе любой .dmg."""
    assets = release.get("assets") or []
    name_env = (os.environ.get("WHISPER_UPDATE_ASSET_NAME") or "").strip()
    dmg_lower = suffix.lower()
    fallback: tuple[str, str] | None = None

    for a in assets:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").strip()
        url = (a.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        if name_env and name == name_env:
            return name, url
        if not name.lower().endswith(dmg_lower):
            continue
        if fallback is None:
            fallback = (name, url)
        if contains and contains.lower() not in name.lower():
            continue
        return name, url

    return fallback
