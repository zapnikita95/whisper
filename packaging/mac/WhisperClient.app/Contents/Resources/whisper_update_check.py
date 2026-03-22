"""Проверка обновлений через GitHub Releases API (без лишних зависимостей)."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def releases_repo() -> str:
    return (os.environ.get("WHISPER_RELEASES_REPO") or "zapnikita95/whisper").strip()


def skip_update_check() -> bool:
    return os.environ.get("WHISPER_SKIP_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes")


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


def fetch_latest_release() -> dict[str, Any] | None:
    if skip_update_check():
        return None
    url = f"https://api.github.com/repos/{releases_repo()}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "WhisperClient/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def pick_asset_url(release: dict[str, Any], *, suffix: str, contains: str | None = None) -> tuple[str, str] | None:
    """Возвращает (имя, url) первого asset с нужным суффиксом."""
    assets = release.get("assets") or []
    name_env = (os.environ.get("WHISPER_UPDATE_ASSET_NAME") or "").strip()
    for a in assets:
        name = (a.get("name") or "").strip()
        url = (a.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        if name_env and name == name_env:
            return name, url
        if not name.lower().endswith(suffix.lower()):
            continue
        if contains and contains.lower() not in name.lower():
            continue
        return name, url
    return None
