"""Параллельный поиск Whisper HTTP API на host (те же правила портов, что pick_server_url)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from whisper_mac_defaults import DEFAULT_SERVER_HOST
except ImportError:
    DEFAULT_SERVER_HOST = "100.115.68.2"


def _priority_ports_in_range(lo: int, hi: int) -> list[int]:
    rng = list(range(lo, hi + 1))
    priority = [8001, 8000]
    seen: set[int] = set()
    out: list[int] = []
    for p in priority:
        if lo <= p <= hi and p not in seen:
            seen.add(p)
            out.append(p)
    for p in rng:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def default_probe_ports() -> list[int]:
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
    return _priority_ports_in_range(lo, hi)


def _max_workers(n_ports: int) -> int:
    raw = (os.environ.get("WHISPER_MAC_SERVER_PROBE_MAX_WORKERS") or "").strip()
    if raw.isdigit():
        return max(1, min(64, int(raw)))
    return max(1, min(12, n_ports))


def check_whisper_port(host: str, port: int, timeout: float) -> tuple[int, str | None]:
    try:
        req = urllib.request.Request(
            f"http://{host}:{port}/",
            headers={"User-Agent": "WhisperMacProbe/1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        d = json.loads(raw)
        if d.get("status") == "ok" and "model" in d:
            return port, f"http://{host}:{port}".rstrip("/")
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


def probe_ports_on_host(
    host: str,
    *,
    timeout: float | None = None,
    ports: list[int] | None = None,
) -> tuple[str | None, str]:
    """Возвращает (URL вида http://host:port или None, короткий текст для UI/лога)."""
    host = (host or "").strip() or DEFAULT_SERVER_HOST
    tmo = float(
        timeout
        if timeout is not None
        else (os.environ.get("WHISPER_MAC_SERVER_PROBE_TIMEOUT") or "2.5").strip()
        or "2.5"
    )
    plist = ports if ports is not None else default_probe_ports()
    if not plist:
        return None, "Список портов для сканирования пуст."

    ok: dict[int, str] = {}
    workers = _max_workers(len(plist))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_whisper_port, host, p, tmo): p for p in plist}
        for fut in as_completed(futures):
            port, url = fut.result()
            if url:
                ok[port] = url

    if not ok:
        return (
            None,
            f"Whisper API не найден на {host} (порты {plist[0]}…{plist[-1]}, таймаут {tmo} с).",
        )

    pref = (os.environ.get("WHISPER_MAC_SERVER_PORT") or "").strip()
    if pref.isdigit():
        pp = int(pref)
        if pp in ok:
            u = ok[pp]
            return u, f"Найден сервер (порт из env): {u}"

    for p in plist:
        if p in ok:
            u = ok[p]
            return u, f"Найден сервер: {u}"

    return None, "Внутренняя ошибка выбора порта."
