"""Compact always-on-top recording HUD (Tk). Safe to call from worker threads."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from typing import Any


class RecordingHud:
    """One compact bar: REC · timer · app · mode."""

    def __init__(self) -> None:
        self._q: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._lock = threading.Lock()

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="whisper-hud", daemon=True)
            self._thread.start()
            self._started.wait(timeout=3.0)

    def show(self, *, app: str | None = None, mode: str | None = None) -> None:
        self._ensure_thread()
        self._q.put(("show", {"app": app or "—", "mode": mode or "auto", "t0": time.monotonic()}))

    def update(self, *, app: str | None = None, mode: str | None = None) -> None:
        self._q.put(("update", {"app": app, "mode": mode}))

    def hide(self) -> None:
        self._q.put(("hide", None))

    def _run(self) -> None:
        root = tk.Tk()
        root.withdraw()
        win = tk.Toplevel(root)
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        win.configure(bg="#111827")
        lbl = tk.Label(
            win,
            text="",
            fg="#e5e7eb",
            bg="#111827",
            font=("Segoe UI", 11, "bold"),
            padx=14,
            pady=8,
        )
        lbl.pack()
        state: dict[str, Any] = {"visible": False, "t0": time.monotonic(), "app": "—", "mode": "auto"}

        def _place() -> None:
            win.update_idletasks()
            w = max(280, win.winfo_reqwidth())
            h = win.winfo_reqheight()
            sw = win.winfo_screenwidth()
            x = max(0, (sw - w) // 2)
            y = 48
            win.geometry(f"{w}x{h}+{x}+{y}")

        def _paint() -> None:
            if not state["visible"]:
                return
            elapsed = int(time.monotonic() - float(state["t0"]))
            mm, ss = divmod(elapsed, 60)
            app = state.get("app") or "—"
            mode = state.get("mode") or "auto"
            if len(str(app)) > 28:
                app = str(app)[:25] + "…"
            lbl.configure(text=f"● REC  {mm:02d}:{ss:02d}  ·  {app}  ·  {mode}")
            _place()

        def _tick() -> None:
            try:
                while True:
                    kind, payload = self._q.get_nowait()
                    if kind == "show":
                        state["visible"] = True
                        state["t0"] = payload.get("t0") or time.monotonic()
                        state["app"] = payload.get("app") or "—"
                        state["mode"] = payload.get("mode") or "auto"
                        win.deiconify()
                        _paint()
                    elif kind == "update":
                        if payload.get("app") is not None:
                            state["app"] = payload["app"] or "—"
                        if payload.get("mode") is not None:
                            state["mode"] = payload["mode"] or "auto"
                        _paint()
                    elif kind == "hide":
                        state["visible"] = False
                        win.withdraw()
            except queue.Empty:
                pass
            if state["visible"]:
                _paint()
            root.after(200, _tick)

        self._started.set()
        root.after(50, _tick)
        root.mainloop()


_hud: RecordingHud | None = None
_hud_lock = threading.Lock()


def get_hud() -> RecordingHud:
    global _hud
    with _hud_lock:
        if _hud is None:
            _hud = RecordingHud()
        return _hud


def hud_show(*, app: str | None = None, mode: str | None = None) -> None:
    try:
        get_hud().show(app=app, mode=mode)
    except Exception:
        pass


def hud_update(*, app: str | None = None, mode: str | None = None) -> None:
    try:
        get_hud().update(app=app, mode=mode)
    except Exception:
        pass


def hud_hide() -> None:
    try:
        get_hud().hide()
    except Exception:
        pass
