"""Tk-диалоги для Whisper Mac menubar: замена медленных osascript display dialog."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from whisper_mac_defaults import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT

_root = None


def _tk_root():
    global _root
    if _root is None:
        import tkinter as tk

        _root = tk.Tk()
        _root.withdraw()
        try:
            _root.overrideredirect(False)
        except tk.TclError:
            pass
    return _root


def mac_tk_ask_string(
    *,
    title: str,
    message: str,
    default: str = "",
    password: bool = False,
) -> str | None:
    """Одна строка ввода. None = отмена; иначе текст (может быть пустым при OK)."""
    import tkinter as tk
    from tkinter import ttk

    root = _tk_root()
    result: list[str | None] = [None]
    win = tk.Toplevel(root)
    win.title(title)
    win.transient(root)
    win.attributes("-topmost", True)
    win.resizable(True, False)

    frm = ttk.Frame(win, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frm, text=message, wraplength=460).pack(anchor=tk.W)
    ent = ttk.Entry(frm, width=52, show="*" if password else "")
    ent.pack(fill=tk.X, pady=(8, 12))
    ent.insert(0, default)
    ent.focus_set()
    ent.selection_range(0, tk.END)

    def ok() -> None:
        result[0] = ent.get()
        win.destroy()

    def cancel() -> None:
        result[0] = None
        win.destroy()

    bf = ttk.Frame(frm)
    bf.pack(fill=tk.X)
    ttk.Button(bf, text="Отмена", command=cancel).pack(side=tk.RIGHT, padx=(4, 0))
    ttk.Button(bf, text="Сохранить", command=ok).pack(side=tk.RIGHT)

    win.protocol("WM_DELETE_WINDOW", cancel)
    win.bind("<Return>", lambda e: ok())
    win.bind("<Escape>", lambda e: cancel())
    win.update_idletasks()
    win.grab_set()
    try:
        win.lift()
        win.focus_force()
    except tk.TclError:
        pass
    root.wait_window(win)
    return result[0]


def _test_whisper_server(host: str, port: int) -> tuple[bool, str]:
    host = host.strip()
    if not host:
        return False, "Укажи IP или имя хоста."
    try:
        p = int(port)
        if not (1 <= p <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        return False, "Порт должен быть числом 1–65535."
    url = f"http://{host}:{p}/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WhisperMacTest/1"})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        d = json.loads(raw)
        if d.get("status") == "ok" and "model" in d:
            return True, f"Ок: {url}\nМодель: {d.get('model', '?')}"
        return False, "Ответ не похож на Whisper Server (ожидался JSON status=ok, model)."
    except Exception as e:
        return False, str(e)[:240]


def mac_tk_server_host_port_dialog(
    *,
    title: str,
    host: str,
    port: int,
    on_test: Callable[[str, int], tuple[bool, str]] | None = None,
) -> tuple[str, int] | None:
    """Два поля + Проверить + Сохранить. Возвращает (host, port) или None."""
    import tkinter as tk
    from tkinter import ttk

    tester = on_test or _test_whisper_server

    root = _tk_root()
    result: list[tuple[str, int] | None] = [None]
    win = tk.Toplevel(root)
    win.title(title)
    win.transient(root)
    win.attributes("-topmost", True)
    win.resizable(False, False)

    frm = ttk.Frame(win, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)
    ttk.Label(
        frm,
        text=(
            "Адрес ПК с Whisper Server в Tailscale/LAN.\n"
            "На экране сервера 127.0.0.1 — это только локально на том ПК; для Mac нужен IP вида 100.x или локальной сети."
        ),
        wraplength=460,
    ).pack(anchor=tk.W)

    hf = ttk.Frame(frm)
    hf.pack(fill=tk.X, pady=(10, 4))
    ttk.Label(hf, text="IP или хост:", width=14).pack(side=tk.LEFT)
    he = ttk.Entry(hf, width=36)
    he.pack(side=tk.LEFT, fill=tk.X, expand=True)
    he.insert(0, host.strip() or DEFAULT_SERVER_HOST)

    pf = ttk.Frame(frm)
    pf.pack(fill=tk.X, pady=(4, 8))
    ttk.Label(pf, text="Порт:", width=14).pack(side=tk.LEFT)
    pe = ttk.Entry(pf, width=10)
    pe.pack(side=tk.LEFT)
    pe.insert(0, str(port if port else DEFAULT_SERVER_PORT))

    status = tk.Text(frm, height=4, width=54, wrap=tk.WORD, state=tk.DISABLED)
    status.pack(fill=tk.X, pady=(0, 8))

    def set_status(text: str) -> None:
        status.configure(state=tk.NORMAL)
        status.delete("1.0", tk.END)
        status.insert(tk.END, text)
        status.configure(state=tk.DISABLED)

    def do_test() -> None:
        try:
            ph = int(str(pe.get()).strip())
        except ValueError:
            set_status("Порт: введи число.")
            return
        ok, msg = tester(he.get().strip(), ph)
        set_status(("✓ " if ok else "✗ ") + msg)

    def save() -> None:
        h = he.get().strip()
        if not h:
            set_status("Укажи IP или хост.")
            return
        try:
            pr = int(str(pe.get()).strip())
            if not (1 <= pr <= 65535):
                raise ValueError
        except ValueError:
            set_status("Порт: число 1–65535.")
            return
        result[0] = (h, pr)
        win.destroy()

    def cancel() -> None:
        result[0] = None
        win.destroy()

    bf = ttk.Frame(frm)
    bf.pack(fill=tk.X)
    ttk.Button(bf, text="Отмена", command=cancel).pack(side=tk.RIGHT, padx=(4, 0))
    ttk.Button(bf, text="Сохранить", command=save).pack(side=tk.RIGHT)
    ttk.Button(bf, text="Проверить", command=do_test).pack(side=tk.RIGHT, padx=(0, 8))

    he.focus_set()
    win.protocol("WM_DELETE_WINDOW", cancel)
    win.bind("<Escape>", lambda e: cancel())
    win.update_idletasks()
    win.grab_set()
    try:
        win.lift()
        win.focus_force()
    except tk.TclError:
        pass
    root.wait_window(win)
    return result[0]


def mac_tk_three_numbers_dialog(
    *,
    title: str,
    message: str,
    default_text: str,
) -> str | None:
    """Одно поле: три числа через пробел. None = отмена."""
    return mac_tk_ask_string(title=title, message=message, default=default_text)


def mac_tk_one_float_dialog(
    *,
    title: str,
    message: str,
    default_text: str,
) -> str | None:
    return mac_tk_ask_string(title=title, message=message, default=default_text)
