#!/usr/bin/env python3
"""
Whisper Hotkey (Windows): окно + Ctrl+Win — запись, отпусти — текст в активное окно.
Сборка exe: packaging/build-hotkey-gui-exe.bat
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

if sys.platform != "win32":
    print("whisper_hotkey_gui.py только для Windows.", file=sys.stderr)
    sys.exit(1)


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = _project_root()
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from whisper_version import get_version as _get_app_version
except ImportError:
    def _get_app_version() -> str:
        return "0.0.0-dev"


PREFS_PATH = ROOT / "whisper_hotkey_gui_prefs.json"


def _load_prefs() -> dict:
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_prefs(data: dict) -> None:
    try:
        PREFS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> int:
    import tkinter as tk
    from tkinter import ttk

    from whisper_models import MODEL_PRESETS, resolve_model

    prefs = _load_prefs()
    saved_key = str(prefs.get("model_key", "large-v3")).strip() or "large-v3"
    preset_keys = [k for k, _, _ in MODEL_PRESETS]
    if saved_key not in preset_keys:
        saved_key = "large-v3"
    label_by_key = {k: lbl for k, _, lbl in MODEL_PRESETS}

    app_ver = _get_app_version()
    root = tk.Tk()
    root.title(f"Whisper Hotkey  v{app_ver}")
    root.geometry("520x400")
    root.minsize(460, 360)

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frm, text="Голос в текст на этом ПК", font=("Segoe UI", 14, "bold")).pack(anchor=tk.W)
    ttk.Label(
        frm,
        text="Удерживай Ctrl+Win — идёт запись (звук), отпусти — распознавание и вставка в активное окно.",
        wraplength=480,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(6, 12))

    admin_ok = _is_admin()
    admin_lbl = ttk.Label(
        frm,
        text="Права администратора: да — перехват клавиш обычно работает."
        if admin_ok
        else "Внимание: без прав администратора Ctrl+Win может не сработать. Закрой программу → ПКМ по exe → «Запуск от имени администратора».",
        wraplength=480,
        justify=tk.LEFT,
        foreground="#0a6" if admin_ok else "#a60",
    )
    admin_lbl.pack(anchor=tk.W, pady=(0, 10))

    ttk.Label(frm, text="Модель (faster-whisper)", font=("", 11, "bold")).pack(anchor=tk.W)
    model_var = tk.StringVar(value=label_by_key[saved_key])
    combo = ttk.Combobox(
        frm,
        textvariable=model_var,
        values=[lbl for _, _, lbl in MODEL_PRESETS],
        state="readonly",
        width=62,
    )
    combo.pack(anchor=tk.W, pady=(4, 8))
    try:
        combo.current(preset_keys.index(saved_key))
    except (ValueError, tk.TclError):
        pass

    def _model_key_from_ui() -> str:
        cur = model_var.get()
        for k, _, lbl in MODEL_PRESETS:
            if lbl == cur:
                return k
        return "large-v3"

    state_lbl = ttk.Label(frm, text="Нажми «Включить Ctrl+Win», чтобы начать.", font=("Segoe UI", 11))
    state_lbl.pack(anchor=tk.W, pady=(8, 4))

    hook_started = {"ok": False}

    def set_state(text: str) -> None:
        def _do() -> None:
            state_lbl.config(text=text)

        try:
            root.after(0, _do)
        except tk.TclError:
            pass

    def run_hook_thread() -> None:
        from whisper_hotkey_core import WhisperHotkey

        os.environ["WHISPER_MODEL"] = _model_key_from_ui()

        def cb(msg: str) -> None:
            set_state(msg)

        service = WhisperHotkey(
            model=resolve_model(os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"),
            device=os.environ.get("WHISPER_DEVICE", "cuda").strip() or "cuda",
            compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
            language=(
                os.environ.get("WHISPER_LANGUAGE", "").strip() or None
            ),
            status_callback=cb,
        )
        try:
            service.run()
        except Exception as e:
            set_state(f"Ошибка: {e}")

    def on_start() -> None:
        if hook_started["ok"]:
            return
        hook_started["ok"] = True
        key = _model_key_from_ui()
        _save_prefs({"model_key": key})
        os.environ["WHISPER_MODEL"] = key
        combo.configure(state="disabled")
        start_btn.state(["disabled"])
        threading.Thread(target=run_hook_thread, name="whisper-hotkey", daemon=True).start()

    start_btn = ttk.Button(frm, text="Включить Ctrl+Win", command=on_start)
    start_btn.pack(anchor=tk.W, pady=(4, 12))

    ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
    ttk.Label(
        frm,
        text="Удалённый Mac / другой ПК → HTTP-сервер: отдельная программа «Whisper GPU Server» (WhisperServer.exe).",
        wraplength=480,
        justify=tk.LEFT,
        foreground="#555",
        font=("", 9),
    ).pack(anchor=tk.W, pady=(0, 12))

    def on_quit() -> None:
        os._exit(0)

    ttk.Button(frm, text="Выход", command=on_quit).pack(anchor=tk.W)

    root.protocol("WM_DELETE_WINDOW", on_quit)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
