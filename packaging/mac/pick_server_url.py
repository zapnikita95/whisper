#!/usr/bin/env python3
"""Ищет whisper API на HOST:8000–8010 (параллельно — иначе до 33 с ожидания и кажется, что .app «мёртвый»)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

HOST = os.environ.get("WHISPER_MAC_SERVER_HOST", "100.115.68.2")
TIMEOUT = 2


def check_port(port: int) -> str | None:
    try:
        out = subprocess.check_output(
            [
                "curl",
                "-sf",
                "--connect-timeout",
                str(TIMEOUT),
                f"http://{HOST}:{port}/",
            ],
            timeout=TIMEOUT + 2,
        )
        d = json.loads(out.decode())
        if d.get("status") == "ok" and "model" in d:
            return f"http://{HOST}:{port}"
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        OSError,
    ):
        pass
    return None


def main() -> int:
    ports = list(range(8000, 8011))
    with ThreadPoolExecutor(max_workers=len(ports)) as ex:
        futures = {ex.submit(check_port, p): p for p in ports}
        for fut in as_completed(futures):
            url = fut.result()
            if url:
                print(url, end="")
                return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
