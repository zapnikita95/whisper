#!/usr/bin/env python3
"""Ищет whisper API на HOST в диапазоне портов (параллельно).

Логика сканирования — whisper_mac_server_probe.probe_ports_on_host (рядом со скриптом или в корне репо).
"""
from __future__ import annotations

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
    from whisper_mac_defaults import DEFAULT_SERVER_HOST
except ImportError:
    DEFAULT_SERVER_HOST = "100.115.68.2"

HOST = os.environ.get("WHISPER_MAC_SERVER_HOST", DEFAULT_SERVER_HOST)


def pick_url() -> str | None:
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
