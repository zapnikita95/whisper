"""Tk settings window for Whisper Hotkey (left-click tray icon — like Mac menu bar)."""
from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, scrolledtext, ttk

_window_lock = threading.Lock()
_window_thread: threading.Thread | None = None


def _run_in_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="whisper-hotkey-ui", daemon=True).start()


def launch_settings_window(
    *,
    version: str,
    paste_mode: str,
    on_paste_mode: Callable[[str], None],
    on_history_file: Callable[[], None],
    on_logs: Callable[[], None],
    on_updates: Callable[[], None],
    on_quit: Callable[[], None],
    on_show_tray_menu: Callable[[], None],
) -> None:
    """Open settings UI in a background thread (safe from pystray)."""
    global _window_thread
    with _window_lock:
        if _window_thread is not None and _window_thread.is_alive():
            # Second click: poke existing window via a one-shot flag is hard; open another Toplevel is ok.
            pass

    def worker() -> None:
        global _window_thread
        try:
            from whisper_hotkey_history import load_history, preview_title

            root = tk.Tk()
            root.title(f"Whisper Hotkey — settings")
            root.geometry("480x620")
            root.minsize(420, 520)

            try:
                root.iconbitmap(default="")  # avoid default python icon if possible
            except tk.TclError:
                pass
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
            ).pack(anchor=tk.W, pady=(2, 10))

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
            hist.configure(state=tk.NORMAL)
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
            ttk.Label(
                frm,
                text="Right-click the tray icon for the full menu (same as Mac menubar).",
                foreground="#666",
                wraplength=440,
            ).pack(anchor=tk.W, pady=(8, 0))

            quit_row = ttk.Frame(frm)
            quit_row.pack(fill=tk.X, pady=(14, 0))
            ttk.Button(quit_row, text="Quit Whisper Hotkey", command=lambda: on_quit()).pack(side=tk.RIGHT)

            root.protocol("WM_DELETE_WINDOW", root.destroy)
            root.mainloop()
        finally:
            with _window_lock:
                _window_thread = None

    with _window_lock:
        _window_thread = threading.Thread(target=worker, name="whisper-settings-win", daemon=True)
        _window_thread.start()
