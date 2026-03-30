"""Проверка обновлений через GitHub Releases API (без лишних зависимостей).

Без токена лимит ~60 запросов/час с одного IP — при частых проверках возможен 403.
Задай WHISPER_GITHUB_TOKEN (classic PAT с read access к public repo или fine-grained read contents).
Результат кэшируется на диске на 1 час, чтобы не исчерпывать лимит при частых запусках.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

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


def fetch_latest_release(*, force: bool = False) -> dict[str, Any] | None:
    """Получить последний релиз из GitHub API.

    force=True: игнорировать кэш (для ручной проверки из меню).
    Автоматическая проверка при старте кэшируется на 1 час.
    При 403 (rate limit) возвращает кэшированные данные если есть.
    """
    if skip_update_check():
        return None

    ttl = _CACHE_TTL_MANUAL if force else _CACHE_TTL_AUTO
    if not force:
        cached = _read_cache()
        if cached and isinstance(cached, dict):
            age = time.time() - float(cached.get("ts", 0))
            if age < ttl:
                return cached.get("release")

    url = f"https://api.github.com/repos/{releases_repo()}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "WhisperClient/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (
        os.environ.get("WHISPER_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    ).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode())
            _write_cache(release)
            return release
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # Rate limit — отдаём кэш если есть
            cached = _read_cache()
            if cached and isinstance(cached, dict) and cached.get("release"):
                return cached["release"]
        # 404 = нет релизов или приватный репо без токена
        return None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        # Сеть недоступна — отдаём кэш
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
