#!/usr/bin/env python3
"""Ищет whisper API на 100.115.68.2:8000–8010, печатает URL в stdout."""
from __future__ import annotations

import json
import subprocess
import sys

HOST = "100.115.68.2"
TIMEOUT = 3


def main() -> int:
    for p in range(8000, 8011):
        try:
            out = subprocess.check_output(
                [
                    "curl",
                    "-sf",
                    "--connect-timeout",
                    str(TIMEOUT),
                    f"http://{HOST}:{p}/",
                ],
                timeout=TIMEOUT + 2,
            )
            d = json.loads(out.decode())
            if d.get("status") == "ok" and "model" in d:
                print(f"http://{HOST}:{p}", end="")
                return 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
