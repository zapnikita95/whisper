#!/usr/bin/env python3
"""
Окно Whisper GPU Server (Windows): порт, подсказка по Ctrl+Win, список HTTP-клиентов (Mac и др.).
Запуск без консоли: собрать exe через PyInstaller (см. packaging/build-server-gui-exe.bat).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform != "win32":
    print("whisper_server_gui.py рассчитан на Windows.", file=sys.stderr)
    sys.exit(1)


def _project_root() -> Path:
    """Каталог рядом с exe (PyInstaller onedir: dist/WhisperServer/). server_port.txt пишется туда же."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _project_root()
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _find_free_port() -> int:
    ps = (
        "$port=8000; "
        "while (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) { $port++ }; "
        "$port"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return int(r.stdout.strip())


def _firewall_allow(port: int) -> None:
    name = f"Whisper Server {port}"
    chk = subprocess.run(
        f'netsh advfirewall firewall show rule name="{name}"',
        shell=True,
        capture_output=True,
    )
    if chk.returncode != 0:
        subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={name}",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={port}",
            ],
            capture_output=True,
        )


def _tailscale_ipv4() -> str:
    try:
        r = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def _write_port_file(port: int) -> None:
    try:
        (ROOT / "server_port.txt").write_text(str(port), encoding="utf-8")
    except OSError:
        pass


def _fetch_clients_json(port: int) -> dict | None:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/clients")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _run_uvicorn(port: int, host: str, ready_event: threading.Event) -> None:
    import uvicorn
    from whisper_server import app

    ready_event.set()
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> int:
    import tkinter as tk
    from tkinter import ttk

    port = _find_free_port()
    _firewall_allow(port)
    _write_port_file(port)
    ts_ip = _tailscale_ipv4()

    ready = threading.Event()
    srv_thread = threading.Thread(
        target=lambda: _run_uvicorn(port, "0.0.0.0", ready),
        name="uvicorn",
        daemon=True,
    )
    srv_thread.start()
    ready.wait(timeout=30)

    root = tk.Tk()
    root.title("Whisper GPU Server")
    root.geometry("560x420")
    root.minsize(480, 360)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frm, text="HTTP API (удалённые клиенты)", font=("", 12, "bold")).pack(anchor=tk.W)
    ttk.Label(frm, text=f"Порт: {port}   •   Локально: http://127.0.0.1:{port}/").pack(anchor=tk.W, pady=(4, 0))

    lan_line = f"В сети (0.0.0.0:{port}) — подключай Mac / другие ПК по IP этого компьютера."
    if ts_ip:
        lan_line += f"\nTailscale IPv4: {ts_ip}  →  URL для Mac: http://{ts_ip}:{port}/"
    ttk.Label(frm, text=lan_line, wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 12))

    ttk.Label(frm, text="Запись голоса на этом ПК (Windows)", font=("", 12, "bold")).pack(anchor=tk.W)
    hotkey_txt = (
        "Отдельная программа whisper-hotkey.py (или start-whisper-hotkey.bat):\n"
        "зажми Ctrl+Win — запись с микрофона, отпусти — распознавание и вставка текста.\n"
        "Это не HTTP: клавиши обрабатываются локально, сервер выше — для Mac и прочих клиентов."
    )
    ttk.Label(frm, text=hotkey_txt, wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 12))

    ttk.Label(frm, text="Недавние HTTP-клиенты (POST /transcribe)", font=("", 12, "bold")).pack(anchor=tk.W)
    cols = ("ip", "client", "sec")
    tree = ttk.Treeview(frm, columns=cols, show="headings", height=8)
    tree.heading("ip", text="IP")
    tree.heading("client", text="Клиент (заголовок)")
    tree.heading("sec", text="Сек назад")
    tree.column("ip", width=140)
    tree.column("client", width=120)
    tree.column("sec", width=80)
    tree.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

    status = ttk.Label(frm, text="Сервер запущен. Закрой окно — остановка.", foreground="#0a0")
    status.pack(anchor=tk.W)

    def refresh_tree() -> None:
        for i in tree.get_children():
            tree.delete(i)
        data = _fetch_clients_json(port)
        if data:
            for row in data.get("clients", []):
                tree.insert(
                    "",
                    tk.END,
                    values=(row.get("ip", ""), row.get("client", ""), row.get("last_seen_ago_sec", "")),
                )
        root.after(1500, refresh_tree)

    refresh_tree()

    def on_close() -> None:
        status.config(text="Остановка…", foreground="#a00")
        root.update_idletasks()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
