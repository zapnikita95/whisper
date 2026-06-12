#!/usr/bin/env python3
"""URL сервера для run.sh: сначала ~/.whisper/mac_client_prefs.json, иначе скан портов."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
_repo_root = _here.parent.parent
if (_repo_root / "whisper_mac_server_probe.py").is_file():
    sys.path.insert(0, str(_repo_root))

from whisper_mac_server_probe import probe_ports_on_host  # noqa: E402

try:
    from whisper_mac_defaults import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT
except ImportError:
    DEFAULT_SERVER_HOST = "100.115.68.2"
    DEFAULT_SERVER_PORT = 8001

HOST = os.environ.get("WHISPER_MAC_SERVER_HOST", DEFAULT_SERVER_HOST)


def _url_from_prefs() -> str | None:
    path = Path.home() / ".whisper" / "mac_client_prefs.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    su = raw.get("server_url")
    if isinstance(su, str):
        s = su.strip().rstrip("/")
        if s.startswith(("http://", "https://")):
            return s
    sh = raw.get("server_host")
    sp = raw.get("server_port")
    host = sh.strip() if isinstance(sh, str) else ""
    port: int | None = None
    if sp is not None:
        try:
            port = int(sp)
        except (TypeError, ValueError):
            port = None
    if host:
        pnum = port if port is not None and 1 <= port <= 65535 else DEFAULT_SERVER_PORT
        return f"http://{host}:{pnum}".rstrip("/")
    if port is not None and 1 <= port <= 65535:
        return f"http://{DEFAULT_SERVER_HOST}:{port}".rstrip("/")
    return None


def pick_url() -> str | None:
    u = _url_from_prefs()
    if u:
        return u
    u, _summ = probe_ports_on_host(HOST)
    return u


def main() -> int:
    u = pick_url()
    if u:
        print(u, end="")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
