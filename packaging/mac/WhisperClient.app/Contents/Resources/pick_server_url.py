#!/usr/bin/env python3
"""Ищет whisper API на HOST в диапазоне портов (параллельно).

Порядок выбора при нескольких ответах:
  1) WHISPER_MAC_SERVER_PORT — если этот порт отвечает как Whisper, берём его;
  2) иначе минимальный порт среди успешных (стабильно: «первый свободный снизу»).

Диапазон: WHISPER_MAC_SERVER_PROBE_FROM / WHISPER_MAC_SERVER_PROBE_TO (по умолчанию 8000–8020),
или WHISPER_MAC_SERVER_PROBE_PORTS="8001,8000,8020" (перекрывает from/to).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HOST = os.environ.get("WHISPER_MAC_SERVER_HOST", "100.115.68.2")
TIMEOUT = float((os.environ.get("WHISPER_MAC_SERVER_PROBE_TIMEOUT") or "2.5").strip() or "2.5")


def _probe_port_list() -> list[int]:
    raw = (os.environ.get("WHISPER_MAC_SERVER_PROBE_PORTS") or "").strip()
    if raw:
        out: list[int] = []
        for part in raw.replace(",", " ").split():
            try:
                out.append(int(part.strip()))
            except ValueError:
                continue
        return sorted(set(p for p in out if 1 <= p <= 65535))
    lo = int((os.environ.get("WHISPER_MAC_SERVER_PROBE_FROM") or "8000").strip() or "8000")
    hi = int((os.environ.get("WHISPER_MAC_SERVER_PROBE_TO") or "8020").strip() or "8020")
    if lo > hi:
        lo, hi = hi, lo
    hi = min(hi, 65535)
    lo = max(lo, 1)
    return list(range(lo, hi + 1))


def check_port(port: int) -> tuple[int, str | None]:
    try:
        req = urllib.request.Request(
            f"http://{HOST}:{port}/",
            headers={"User-Agent": "WhisperMacPick/1"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        d = json.loads(raw)
        if d.get("status") == "ok" and "model" in d:
            return port, f"http://{HOST}:{port}"
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        pass
    return port, None


def pick_url() -> str | None:
    ports = _probe_port_list()
    if not ports:
        return None
    ok: dict[int, str] = {}
    max_workers = min(32, max(1, len(ports)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(check_port, p): p for p in ports}
        for fut in as_completed(futures):
            port, url = fut.result()
            if url:
                ok[port] = url
    if not ok:
        return None
    pref = (os.environ.get("WHISPER_MAC_SERVER_PORT") or "").strip()
    if pref.isdigit():
        pp = int(pref)
        if pp in ok:
            return ok[pp]
    return ok[min(ok)]


def main() -> int:
    u = pick_url()
    if u:
        print(u, end="")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
