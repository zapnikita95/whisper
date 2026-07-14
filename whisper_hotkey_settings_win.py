"""Tk settings window for Whisper Hotkey — Mac-like options without tray icon."""
from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, scrolledtext, simpledialog, ttk

_window_lock = threading.Lock()
_window_thread: threading.Thread | None = None


def _scrollable_parent(parent: tk.Misc) -> tuple[ttk.Frame, ttk.Frame]:
    """Canvas + inner frame for long settings forms."""
    outer = ttk.Frame(parent)
    canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas.create_window((0, 0), window=inner, anchor=tk.NW)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_mousewheel(event: tk.Event) -> None:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")
    return outer, inner


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
    on_prefs_saved: Callable[[], None] | None = None,
    standalone: bool = False,
    blocking: bool = False,
) -> None:
    """Open settings UI. Use blocking=True for --settings (no tray process)."""

    def worker() -> None:
        global _window_thread
        try:
            from whisper_groq import (
                groq_api_key_from_env,
                groq_is_configured,
                load_hotkey_prefs,
                read_hotkey_groq_api_key_pref,
                resolve_groq_proxy_url,
                resolve_transcribe_backend_mode,
                save_hotkey_prefs,
            )
            from whisper_hotkey_history import load_history, preview_title
            from whisper_models import MODEL_PRESETS
            from whisper_system_profile import nvidia_vram_snapshot

            prefs = load_hotkey_prefs()

            def _merge_save(**kwargs: object) -> None:
                nonlocal prefs
                prefs = {**prefs, **kwargs}
                save_hotkey_prefs(prefs)
                if on_prefs_saved:
                    on_prefs_saved()

            root = tk.Tk()
            root.title("Whisper Hotkey — settings")
            root.geometry("540x720")
            root.minsize(480, 560)

            try:
                root.attributes("-topmost", True)
            except tk.TclError:
                pass

            shell = ttk.Frame(root, padding=10)
            shell.pack(fill=tk.BOTH, expand=True)

            scroll_outer, frm = _scrollable_parent(shell)
            scroll_outer.pack(fill=tk.BOTH, expand=True)

            ttk.Label(frm, text="Whisper Hotkey", font=("Segoe UI", 15, "bold")).pack(anchor=tk.W)
            ttk.Label(
                frm,
                text=f"v{version}  ·  Hold Ctrl+Win to record",
                foreground="#444",
            ).pack(anchor=tk.W, pady=(2, 6))

            ttk.Label(
                frm,
                text="Most options need a restart of Whisper Hotkey to take effect.",
                foreground="#666",
                wraplength=480,
            ).pack(anchor=tk.W, pady=(0, 8))

            # —— GPU / VRAM ——
            vram_lbl = ttk.Label(frm, text="", foreground="#333", wraplength=480)
            vram_lbl.pack(anchor=tk.W, pady=(0, 6))

            def _refresh_vram() -> None:
                snap = nvidia_vram_snapshot()
                if not snap.get("has_nvidia_gpu"):
                    vram_lbl.configure(text="GPU: NVIDIA not detected (auto mode will use Groq if configured).")
                    return
                name = snap.get("gpu_name") or "NVIDIA GPU"
                total = snap.get("vram_total_gb")
                free = snap.get("vram_free_gb")
                total_s = f"{total:.1f}" if total is not None else "?"
                free_s = f"{free:.2f}" if free is not None else "?"
                vram_lbl.configure(text=f"GPU: {name}  ·  VRAM {free_s} GB free / {total_s} GB total")

            ttk.Button(frm, text="Refresh GPU memory", command=_refresh_vram).pack(anchor=tk.W, pady=(0, 8))
            _refresh_vram()

            # —— Transcription backend ——
            ttk.Label(frm, text="Transcription", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
            cur_backend = resolve_transcribe_backend_mode(
                prefs.get("transcribe_backend") if isinstance(prefs.get("transcribe_backend"), str) else None,
                "WHISPER_TRANSCRIBE_BACKEND",
                "WHISPER_MAC_TRANSCRIBE_BACKEND",
            )
            backend_var = tk.StringVar(value=cur_backend)
            backend_specs = [
                ("auto_vram", "Auto — local GPU if enough free VRAM, else Groq"),
                ("server", "Local GPU only"),
                ("groq", "Groq only (whisper-large-v3)"),
                ("server_then_groq", "Local GPU, then Groq fallback"),
                ("groq_then_server", "Groq, then local GPU fallback"),
            ]

            def _apply_backend() -> None:
                _merge_save(transcribe_backend=backend_var.get())

            for mode, label in backend_specs:
                ttk.Radiobutton(
                    frm, text=label, variable=backend_var, value=mode, command=_apply_backend
                ).pack(anchor=tk.W, pady=1)

            margin_row = ttk.Frame(frm)
            margin_row.pack(anchor=tk.W, pady=(4, 8), fill=tk.X)
            ttk.Label(margin_row, text="Auto VRAM safety margin (GB):").pack(side=tk.LEFT)
            margin_var = tk.StringVar(
                value=str(prefs.get("auto_vram_margin_gb", "") or "0.8")
            )

            def _apply_margin() -> None:
                s = margin_var.get().strip().replace(",", ".")
                if not s:
                    p = load_hotkey_prefs()
                    p.pop("auto_vram_margin_gb", None)
                    save_hotkey_prefs(p)
                    return
                try:
                    _merge_save(auto_vram_margin_gb=float(s))
                except ValueError:
                    messagebox.showerror("VRAM margin", "Enter a number, e.g. 0.8", parent=root)

            ttk.Entry(margin_row, textvariable=margin_var, width=6).pack(side=tk.LEFT, padx=(6, 4))
            ttk.Button(margin_row, text="Save", command=_apply_margin).pack(side=tk.LEFT)

            # —— Model ——
            ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
            ttk.Label(frm, text="Whisper model (local GPU)", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
            model_keys = [k for k, _, _ in MODEL_PRESETS]
            cur_model = str(prefs.get("model_key", "large-v3")).strip() or "large-v3"
            if cur_model not in model_keys:
                cur_model = "large-v3"
            model_var = tk.StringVar(value=cur_model)
            model_combo = ttk.Combobox(
                frm,
                textvariable=model_var,
                values=model_keys,
                state="readonly",
                width=42,
            )
            model_combo.pack(anchor=tk.W, pady=(4, 8))

            def _apply_model(_event: object = None) -> None:
                _merge_save(model_key=model_var.get())

            model_combo.bind("<<ComboboxSelected>>", _apply_model)

            # —— Groq ——
            ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
            ttk.Label(frm, text="Groq API", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
            groq_status = ttk.Label(frm, text="", foreground="#555", wraplength=480)
            groq_status.pack(anchor=tk.W, pady=(2, 6))

            def _groq_status_text() -> str:
                if groq_api_key_from_env():
                    return "Groq key: from .env / environment (overrides prefs)."
                if read_hotkey_groq_api_key_pref():
                    return "Groq key: saved in prefs."
                if resolve_groq_proxy_url(prefs.get("groq_proxy_url") if isinstance(prefs.get("groq_proxy_url"), str) else None):
                    return "Groq: Railway proxy configured (key may live on server)."
                return "Groq: not configured — set API key or proxy URL."

            groq_status.configure(text=_groq_status_text())

            groq_row = ttk.Frame(frm)
            groq_row.pack(fill=tk.X, pady=2)

            def _edit_groq_key() -> None:
                ans = simpledialog.askstring(
                    "Groq API key",
                    "Key gsk_…  (empty + OK removes from prefs)",
                    show="*",
                    parent=root,
                )
                if ans is None:
                    return
                p = load_hotkey_prefs()
                if not ans.strip():
                    p.pop("groq_api_key", None)
                else:
                    p["groq_api_key"] = ans.strip()
                save_hotkey_prefs(p)
                groq_status.configure(text=_groq_status_text())

            def _use_default_proxy() -> None:
                _merge_save(
                    groq_proxy_enabled=True,
                    groq_proxy_url="https://whisper-groq-proxy-production.up.railway.app",
                )
                groq_status.configure(text=_groq_status_text())

            def _toggle_proxy() -> None:
                p = load_hotkey_prefs()
                cur = p.get("groq_proxy_enabled")
                if isinstance(cur, bool):
                    on = cur
                else:
                    on = True
                _merge_save(groq_proxy_enabled=not on)
                groq_status.configure(text=_groq_status_text())

            ttk.Button(groq_row, text="Groq API key…", command=_edit_groq_key).pack(side=tk.LEFT, padx=(0, 6))
            ttk.Button(groq_row, text="Default Railway proxy", command=_use_default_proxy).pack(
                side=tk.LEFT, padx=(0, 6)
            )
            ttk.Button(groq_row, text="Toggle proxy", command=_toggle_proxy).pack(side=tk.LEFT)

            if not groq_is_configured():
                ttk.Label(
                    frm,
                    text="Tip: with Auto VRAM mode, Groq is used when GPU memory is busy.",
                    foreground="#888",
                    wraplength=480,
                ).pack(anchor=tk.W, pady=(4, 0))

            # —— Voice ——
            ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
            ttk.Label(frm, text="Voice profile", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
            spk_var = tk.BooleanVar(value=bool(prefs.get("speaker_verify", False)))

            def _toggle_spk() -> None:
                _merge_save(speaker_verify=bool(spk_var.get()))

            ttk.Checkbutton(
                frm,
                text="Verify voice against ~/.whisper/speaker_embedding.npy (restart required)",
                variable=spk_var,
                command=_toggle_spk,
            ).pack(anchor=tk.W, pady=2)
            ttk.Label(
                frm,
                text="Record profile: tray menu → Record voice profile (~45 s), or run hotkey from tray.",
                foreground="#888",
                wraplength=480,
            ).pack(anchor=tk.W)

            # —— Notifications ——
            ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
            notif_var = tk.BooleanVar(value=bool(prefs.get("notifications", True)))

            def _toggle_notif() -> None:
                _merge_save(notifications=bool(notif_var.get()))

            ttk.Checkbutton(
                frm,
                text="Windows toast notifications",
                variable=notif_var,
                command=_toggle_notif,
            ).pack(anchor=tk.W)

            # —— Text output ——
            ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
            ttk.Label(frm, text="Text output (restart required)", font=("Segoe UI", 10, "bold")).pack(
                anchor=tk.W
            )
            pm = tk.StringVar(value=paste_mode if paste_mode in ("auto", "clipboard", "history_only") else "auto")

            def _apply_paste() -> None:
                on_paste_mode(pm.get())
                _merge_save(paste_mode=pm.get())

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
            ttk.Button(btn_row, text="Check updates", command=lambda: on_updates()).pack(side=tk.LEFT, padx=(0, 6))
            ttk.Button(
                btn_row,
                text="Tray menu (vocabulary…)",
                command=lambda: on_show_tray_menu(),
            ).pack(side=tk.LEFT)

            ttk.Label(frm, text="Recent transcriptions:", font=("Segoe UI", 10, "bold")).pack(
                anchor=tk.W, pady=(12, 4)
            )
            hist = scrolledtext.ScrolledText(frm, height=8, wrap=tk.WORD, font=("Segoe UI", 9))
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