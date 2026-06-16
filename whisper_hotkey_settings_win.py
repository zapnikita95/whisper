"""Tk settings window for Whisper Hotkey — no tray icon required."""
from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, scrolledtext, ttk

_window_lock = threading.Lock()
_window_thread: threading.Thread | None = None


def launch_settings_window(
    *,
    version: str,
    paste_mode: str,
    show_on_start: bool,
    on_paste_mode: Callable[[str], None],
    on_history_file: Callable[[], None],
    on_logs: Callable[[], None],
    on_updates: Callable[[], None],
    on_quit: Callable[[], None],
    on_show_tray_menu: Callable[[], None],
    on_toggle_show_on_start: Callable[[bool], None] | None = None,
    standalone: bool = False,
    blocking: bool = False,
) -> None:
    """Open settings UI. Use blocking=True for --settings (no tray process)."""

    def worker() -> None:
        global _window_thread
        try:
            from whisper_hotkey_history import load_history, preview_title

            root = tk.Tk()
            root.title("Whisper Hotkey — settings")
            root.geometry("500x640")
            root.minsize(440, 540)

            try:
                root.attributes("-topmost", True)
            except tk.TclError:
                pass

            frm = ttk.Frame(root, padding=14)
            frm.pack(fill=tk.BOTH, expand=True)

            ttk.Label(frm, text="Whisper Hotkey", font=("Segoe UI", 15, "bold")).pack(anchor=tk.W)
            ttk.Label(
                frm,
                text=f"v{version}  ·  Hold Ctrl+Win to record",
                foreground="#444",
            ).pack(anchor=tk.W, pady=(2, 6))

            ttk.Label(
                frm,
                text="Settings live here (and in Start → Whisper Hotkey Settings). "
                "Tray icon may be hidden when running as Administrator.",
                foreground="#666",
                wraplength=460,
            ).pack(anchor=tk.W, pady=(0, 10))

            ttk.Label(
                frm,
                text="Text output (restart Whisper Hotkey after changing):",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor=tk.W)
            pm = tk.StringVar(value=paste_mode if paste_mode in ("auto", "clipboard", "history_only") else "auto")

            def _apply_paste() -> None:
                on_paste_mode(pm.get())

            for mode, label in (
                ("auto", "Paste into active window + clipboard"),
                ("clipboard", "Clipboard only (no paste)"),
                ("history_only", "History only (no paste, no clipboard)"),
            ):
                ttk.Radiobutton(frm, text=label, variable=pm, value=mode, command=_apply_paste).pack(
                    anchor=tk.W, pady=1
                )

            if on_toggle_show_on_start is not None:
                show_var = tk.BooleanVar(value=show_on_start)
                def _toggle_show() -> None:
                    on_toggle_show_on_start(bool(show_var.get()))

                ttk.Checkbutton(
                    frm,
                    text="Open this window when Whisper Hotkey starts",
                    variable=show_var,
                    command=_toggle_show,
                ).pack(anchor=tk.W, pady=(8, 0))

            ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

            btn_row = ttk.Frame(frm)
            btn_row.pack(fill=tk.X)
            ttk.Button(btn_row, text="Open history file", command=lambda: on_history_file()).pack(
                side=tk.LEFT, padx=(0, 6)
            )
            ttk.Button(btn_row, text="Log folder", command=lambda: on_logs()).pack(side=tk.LEFT, padx=(0, 6))
            ttk.Button(btn_row, text="Updates", command=lambda: on_updates()).pack(side=tk.LEFT)

            ttk.Label(frm, text="Recent transcriptions:", font=("Segoe UI", 10, "bold")).pack(
                anchor=tk.W, pady=(12, 4)
            )
            hist = scrolledtext.ScrolledText(frm, height=10, wrap=tk.WORD, font=("Segoe UI", 9))
            hist.pack(fill=tk.BOTH, expand=True)
            entries = load_history(limit=25)
            if entries:
                for e in entries:
                    t = str(e.get("text") or "").strip()
                    if not t:
                        continue
                    mark = "✗ " if e.get("failure") else ""
                    hist.insert(tk.END, mark + preview_title(t, 200) + "\n\n")
            else:
                hist.insert(tk.END, "(No transcriptions yet — use Ctrl+Win.)\n")
            hist.configure(state=tk.DISABLED)

            def copy_hist() -> None:
                try:
                    import pyperclip

                    parts = [str(e.get("text") or "").strip() for e in entries if e.get("text")]
                    if parts:
                        pyperclip.copy("\n\n".join(parts[:5]))
                        messagebox.showinfo("History", "Last entries copied to clipboard.", parent=root)
                except Exception as ex:
                    messagebox.showerror("History", str(ex), parent=root)

            ttk.Button(frm, text="Copy recent to clipboard", command=copy_hist).pack(anchor=tk.W, pady=(6, 0))

            ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

            ttk.Button(
                frm,
                text="More: Groq, models, vocabulary, voice profile…",
                command=lambda: on_show_tray_menu(),
            ).pack(fill=tk.X, pady=2)

            quit_row = ttk.Frame(frm)
            quit_row.pack(fill=tk.X, pady=(14, 0))
            quit_label = "Close" if standalone else "Quit Whisper Hotkey"
            ttk.Button(quit_row, text=quit_label, command=lambda: on_quit()).pack(side=tk.RIGHT)

            def _close() -> None:
                on_quit()
                try:
                    root.destroy()
                except tk.TclError:
                    pass

            root.protocol("WM_DELETE_WINDOW", _close)
            root.mainloop()
        finally:
            with _window_lock:
                _window_thread = None

    if blocking:
        worker()
        return

    with _window_lock:
        if _window_thread is not None and _window_thread.is_alive():
            pass
        _window_thread = threading.Thread(target=worker, name="whisper-settings-win", daemon=True)
        _window_thread.start()
