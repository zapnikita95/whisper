"""Models library tab for Whisper Server GUI (English)."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any, Callable

from whisper_model_hub import download_model, is_model_cached
from whisper_models import MODEL_CATALOG, SPEC_BY_KEY
from whisper_system_profile import detect_system, recommend_model


def _fetch_json(url: str, *, timeout: float = 2.0) -> dict | None:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError, TimeoutError):
        return None


def build_models_tab(
    parent: object,
    root: object,
    port_holder: dict,
    *,
    on_pick_model: Callable[[str], None],
) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    frm = ttk.Frame(parent, padding=8)
    frm.pack(fill=tk.BOTH, expand=True)

    sys_box = ttk.LabelFrame(frm, text="This PC", padding=8)
    sys_box.pack(fill=tk.X, pady=(0, 8))

    sys_var = tk.StringVar(value="Detecting hardware…")
    ttk.Label(sys_box, textvariable=sys_var, wraplength=560, justify=tk.LEFT).pack(anchor=tk.W)

    rec_var = tk.StringVar(value="")
    ttk.Label(sys_box, textvariable=rec_var, wraplength=560, justify=tk.LEFT, foreground="#0a6").pack(
        anchor=tk.W, pady=(6, 0)
    )

    btn_row = ttk.Frame(sys_box)
    btn_row.pack(anchor=tk.W, pady=(8, 0))

    cols = ("key", "label", "langs", "size", "vram", "cached")
    tree = ttk.Treeview(frm, columns=cols, show="headings", height=14)
    tree.heading("key", text="Key")
    tree.heading("label", text="Model")
    tree.heading("langs", text="Languages")
    tree.heading("size", text="Size GB")
    tree.heading("vram", text="Min VRAM")
    tree.heading("cached", text="Cached")
    tree.column("key", width=120)
    tree.column("label", width=220)
    tree.column("langs", width=90)
    tree.column("size", width=60)
    tree.column("vram", width=70)
    tree.column("cached", width=60)
    tree.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

    status_var = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status_var, foreground="#444").pack(anchor=tk.W)

    action_row = ttk.Frame(frm)
    action_row.pack(fill=tk.X)

    refresh_busy = {"v": False}
    iid_by_key: dict[str, str] = {}

    def _selected_key() -> str | None:
        sel = tree.selection()
        if not sel:
            return None
        vals = tree.item(sel[0], "values")
        return str(vals[0]) if vals else None

    def _refresh_rows() -> None:
        for iid in tree.get_children():
            tree.delete(iid)
        iid_by_key.clear()
        for m in MODEL_CATALOG:
            cached = "yes" if is_model_cached(m.key) else "no"
            langs = ", ".join(m.languages)
            iid = tree.insert(
                "",
                tk.END,
                values=(
                    m.key,
                    m.label_en[:48],
                    langs,
                    f"{m.size_gb:.1f}",
                    f"{m.min_vram_gb:.1f}",
                    cached,
                ),
            )
            iid_by_key[m.key] = iid

    def _apply_recommendation(*, prefer_russian: bool = False, prefer_english: bool = False) -> None:
        prof = detect_system()
        gpu = prof.gpu_name or "No NVIDIA GPU"
        vram = f"{prof.vram_gb:.1f} GB" if prof.vram_gb is not None else "n/a"
        sys_var.set(
            f"{prof.os_name} · {prof.cpu_cores} CPU cores · {prof.ram_gb:.0f} GB RAM · "
            f"GPU: {gpu} ({vram} VRAM)"
        )
        rec = recommend_model(prof, prefer_russian=prefer_russian, prefer_english=prefer_english)
        rec_var.set(
            f"Recommended: {rec.model_key} ({rec.compute_type} on {rec.device})\n{rec.reason}"
        )
        iid = iid_by_key.get(rec.model_key)
        if iid:
            tree.selection_set(iid)
            tree.see(iid)

    def on_recommend(_evt: object | None = None) -> None:
        _apply_recommendation()

    def on_recommend_en(_evt: object | None = None) -> None:
        _apply_recommendation(prefer_english=True)

    def on_recommend_ru(_evt: object | None = None) -> None:
        _apply_recommendation(prefer_russian=True)

    def on_use_recommended(_evt: object | None = None) -> None:
        prof = detect_system()
        rec = recommend_model(prof)
        on_pick_model(rec.model_key)
        status_var.set(f"Selected model: {rec.model_key} (restart server to apply)")

    def on_use_selected(_evt: object | None = None) -> None:
        key = _selected_key()
        if not key:
            messagebox.showinfo("Models", "Select a model in the list first.")
            return
        on_pick_model(key)
        status_var.set(f"Selected model: {key} (restart server to apply)")

    def on_download(_evt: object | None = None) -> None:
        key = _selected_key()
        if not key:
            messagebox.showinfo("Models", "Select a model to download.")
            return
        if is_model_cached(key):
            status_var.set(f"{key} is already cached.")
            _refresh_rows()
            return
        status_var.set(f"Downloading {key}… (see whisper_server.log)")

        def worker() -> None:
            err: str | None = None
            try:
                download_model(key)
            except Exception as e:
                err = str(e)

            def done() -> None:
                if err:
                    status_var.set(f"Download failed: {err[:200]}")
                    messagebox.showerror("Download", err[:400])
                else:
                    status_var.set(f"Downloaded: {key}")
                _refresh_rows()

            root.after(0, done)

        threading.Thread(target=worker, name=f"gui-dl-{key}", daemon=True).start()

    def on_refresh_api(_evt: object | None = None) -> None:
        if refresh_busy["v"]:
            return
        refresh_busy["v"] = True
        port = int(port_holder.get("value", 8000))

        def worker() -> None:
            data = _fetch_json(f"http://127.0.0.1:{port}/models/recommend")

            def apply() -> None:
                refresh_busy["v"] = False
                _refresh_rows()
                if data and data.get("status") == "ok":
                    sys_d = data.get("system") or {}
                    rec_d = data.get("recommendation") or {}
                    sys_var.set(
                        f"API · {sys_d.get('cpu_cores', '?')} cores · "
                        f"{sys_d.get('ram_gb', '?')} GB RAM · GPU: "
                        f"{sys_d.get('gpu_name') or 'none'}"
                    )
                    rec_var.set(
                        f"API recommends: {rec_d.get('model_key')} — {rec_d.get('reason', '')}"
                    )
                else:
                    _apply_recommendation()

            root.after(0, apply)

        threading.Thread(target=worker, name="gui-models-api", daemon=True).start()

    ttk.Button(btn_row, text="Recommend (auto)", command=on_recommend).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_row, text="Recommend English", command=on_recommend_en).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_row, text="Recommend Russian", command=on_recommend_ru).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_row, text="Use recommended", command=on_use_recommended).pack(side=tk.LEFT, padx=(0, 6))

    ttk.Button(action_row, text="Download selected", command=on_download).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(action_row, text="Use as server model", command=on_use_selected).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(action_row, text="Refresh list", command=_refresh_rows).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(action_row, text="Refresh from API", command=on_refresh_api).pack(side=tk.LEFT)

    _refresh_rows()
    _apply_recommendation()
