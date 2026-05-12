"""Редактор словаря Whisper для macOS: термины, произношение, замены, контекст.

Не вызывать из rumps callback напрямую — только через after() / отдельный поток,
как остальные Tk-диалоги клиента."""
from __future__ import annotations

import json
import subprocess
from typing import Any

from whisper_vocab import (
    build_initial_prompt,
    load_vocab,
    parse_terms_list,
    save_vocab,
    serialize_term_for_json,
    vocab_file_path,
)


def _tk_root():
    import whisper_mac_tk_dialogs as _mtd

    return _mtd._tk_root()


def open_vocab_editor(*, preview_app_name: str | None = None) -> None:
    """Модальное окно редактирования ~/.whisper/vocab.json (только global)."""
    import tkinter as tk
    from tkinter import ttk

    data = json.loads(json.dumps(load_vocab(force=True)))  # deep copy
    g = data.setdefault("global", {})
    g.setdefault("terms", [])
    g.setdefault("replacements", [])
    g.setdefault("context_hint", "")

    root = _tk_root()
    win = tk.Toplevel(root)
    win.title("Словарь Whisper")
    win.minsize(720, 560)
    win.resizable(True, True)
    win.transient(root)
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass

    # Светлая «карточная» палитра (читается и в светлой теме macOS)
    bg = "#ececf1"
    card = "#fbfbfd"
    fg = "#1d1d1f"
    muted = "#6e6e73"
    accent = "#007aff"
    win.configure(bg=bg)
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=bg, foreground=fg)
    style.configure("TFrame", background=bg)
    style.configure("TLabelframe", background=card, foreground=fg)
    style.configure("TLabelframe.Label", background=card, foreground=fg, font=("SF Pro Text", 12, "bold"))
    style.configure("TLabel", background=bg, foreground=fg, font=("SF Pro Text", 11))
    style.configure("Muted.TLabel", background=bg, foreground=muted, font=("SF Pro Text", 10))
    style.configure("Title.TLabel", background=bg, foreground=fg, font=("SF Pro Text", 18, "bold"))
    style.configure("TNotebook", background=bg)
    style.configure("TNotebook.Tab", padding=(14, 8), font=("SF Pro Text", 11))
    style.configure("Treeview", font=("SF Pro Text", 11), rowheight=26)
    style.configure("Treeview.Heading", font=("SF Pro Text", 11, "bold"))
    style.map("TNotebook.Tab", background=[("selected", card)])

    outer = ttk.Frame(win, padding=(20, 16))
    outer.pack(fill=tk.BOTH, expand=True)

    ttk.Label(outer, text="Словарь", style="Title.TLabel").pack(anchor=tk.W)
    ttk.Label(
        outer,
        text=(
            "Термины и варианты произношения уходят в подсказку модели (initial_prompt) — "
            "так Whisper и Groq чаще выбирают нужные слова. Отдельной фонетической таблицы у API нет.\n"
            "Замены — после распознавания: regex → точный текст."
        ),
        style="Muted.TLabel",
        wraplength=680,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(4, 12))

    nb = ttk.Notebook(outer)
    nb.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

    # ——— Термины ———
    tab_terms = ttk.Frame(nb, padding=12)
    nb.add(tab_terms, text="  Термины  ")

    terms_card = ttk.LabelFrame(tab_terms, text=" Слова для распознавания ", padding=10)
    terms_card.pack(fill=tk.BOTH, expand=True)

    cols = ("term", "aliases", "note")
    tv_terms = ttk.Treeview(terms_card, columns=cols, show="headings", height=14, selectmode="browse")
    tv_terms.heading("term", text="Слово в тексте")
    tv_terms.heading("aliases", text="Как может слышаться (через запятую)")
    tv_terms.heading("note", text="Заметка для модели")
    tv_terms.column("term", width=160, minwidth=80)
    tv_terms.column("aliases", width=260, minwidth=120)
    tv_terms.column("note", width=220, minwidth=80)
    sy = ttk.Scrollbar(terms_card, orient=tk.VERTICAL, command=tv_terms.yview)
    tv_terms.configure(yscrollcommand=sy.set)
    tv_terms.grid(row=0, column=0, sticky="nsew")
    sy.grid(row=0, column=1, sticky="ns")
    terms_card.rowconfigure(0, weight=1)
    terms_card.columnconfigure(0, weight=1)

    form = ttk.Frame(terms_card, padding=(0, 12, 0, 0))
    form.grid(row=1, column=0, columnspan=2, sticky="ew")
    ttk.Label(form, text="Слово").grid(row=0, column=0, sticky=tk.W, pady=(0, 2))
    e_term = ttk.Entry(form, width=28)
    e_term.grid(row=1, column=0, sticky="ew", padx=(0, 8))
    ttk.Label(form, text="Как слышится").grid(row=0, column=1, sticky=tk.W, pady=(0, 2))
    e_alias = ttk.Entry(form, width=36)
    e_alias.grid(row=1, column=1, sticky="ew", padx=(0, 8))
    ttk.Label(form, text="Заметка").grid(row=0, column=2, sticky=tk.W, pady=(0, 2))
    e_note = ttk.Entry(form, width=28)
    e_note.grid(row=1, column=2, sticky="ew")
    form.columnconfigure(0, weight=1)
    form.columnconfigure(1, weight=2)
    form.columnconfigure(2, weight=1)

    def _refresh_terms_tree() -> None:
        for iid in tv_terms.get_children():
            tv_terms.delete(iid)
        for e in parse_terms_list(g.get("terms")):
            tv_terms.insert(
                "",
                tk.END,
                values=(e["term"], ", ".join(e.get("aliases") or []), e.get("note") or ""),
            )

    def _terms_selection_values() -> tuple[str, str, str] | None:
        sel = tv_terms.selection()
        if not sel:
            return None
        return tv_terms.item(sel[0], "values")  # type: ignore[return-value]

    def _add_or_update_term() -> None:
        term = e_term.get().strip()
        if not term:
            return
        aliases_s = e_alias.get().strip()
        note = e_note.get().strip()
        aliases = [a.strip() for a in aliases_s.replace(";", ",").split(",") if a.strip()]
        raw_list: list[Any] = list(g.get("terms") or [])
        entries = parse_terms_list(raw_list)
        new_e = {"term": term, "aliases": aliases, "note": note}
        replaced = False
        out: list[dict[str, Any]] = []
        for e in entries:
            if e["term"].lower() == term.lower():
                out.append(new_e)
                replaced = True
            else:
                out.append(e)
        if not replaced:
            out.append(new_e)
        g["terms"] = [serialize_term_for_json(x) for x in out]
        _refresh_terms_tree()
        _update_preview()
        e_term.delete(0, tk.END)
        e_alias.delete(0, tk.END)
        e_note.delete(0, tk.END)

    def _delete_selected_term() -> None:
        sel = tv_terms.selection()
        if not sel:
            return
        vals = tv_terms.item(sel[0], "values")
        if not vals:
            return
        kill = str(vals[0]).strip().lower()
        raw_list = list(g.get("terms") or [])
        entries = [e for e in parse_terms_list(raw_list) if e["term"].lower() != kill]
        g["terms"] = [serialize_term_for_json(x) for x in entries]
        _refresh_terms_tree()
        _update_preview()

    def _load_term_into_form(_evt=None) -> None:
        v = _terms_selection_values()
        if not v:
            return
        e_term.delete(0, tk.END)
        e_term.insert(0, v[0])
        e_alias.delete(0, tk.END)
        e_alias.insert(0, v[1])
        e_note.delete(0, tk.END)
        e_note.insert(0, v[2])

    def _paste_word() -> None:
        try:
            raw = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2).stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            return
        w = raw.strip().split("\n", 1)[0].strip()
        if w:
            e_term.delete(0, tk.END)
            e_term.insert(0, w)

    tv_terms.bind("<<TreeviewSelect>>", _load_term_into_form)

    bf = ttk.Frame(terms_card)
    bf.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    ttk.Button(bf, text="Добавить / обновить", command=_add_or_update_term).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(bf, text="Удалить выбранное", command=_delete_selected_term).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(bf, text="Вставить слово из буфера", command=_paste_word).pack(side=tk.LEFT)

    # ——— Замены ———
    tab_rep = ttk.Frame(nb, padding=12)
    nb.add(tab_rep, text="  Замены  ")

    rep_card = ttk.LabelFrame(tab_rep, text=" После распознавания (regex → текст) ", padding=10)
    rep_card.pack(fill=tk.BOTH, expand=True)

    rcols = ("from", "to")
    tv_rep = ttk.Treeview(rep_card, columns=rcols, show="headings", height=12, selectmode="browse")
    tv_rep.heading("from", text="Найти (regex)")
    tv_rep.heading("to", text="Заменить на")
    tv_rep.column("from", width=340)
    tv_rep.column("to", width=340)
    sr = ttk.Scrollbar(rep_card, orient=tk.VERTICAL, command=tv_rep.yview)
    tv_rep.configure(yscrollcommand=sr.set)
    tv_rep.grid(row=0, column=0, sticky="nsew")
    sr.grid(row=0, column=1, sticky="ns")
    rep_card.rowconfigure(0, weight=1)
    rep_card.columnconfigure(0, weight=1)

    rform = ttk.Frame(rep_card, padding=(0, 10, 0, 0))
    rform.grid(row=1, column=0, columnspan=2, sticky="ew")
    ttk.Label(rform, text="Regex").grid(row=0, column=0, sticky=tk.W)
    rf_from = ttk.Entry(rform, width=48)
    rf_from.grid(row=1, column=0, sticky="ew", padx=(0, 8))
    ttk.Label(rform, text="На что заменить").grid(row=0, column=1, sticky=tk.W)
    rf_to = ttk.Entry(rform, width=40)
    rf_to.grid(row=1, column=1, sticky="ew")
    rform.columnconfigure(0, weight=1)
    rform.columnconfigure(1, weight=1)

    def _refresh_rep_tree() -> None:
        for iid in tv_rep.get_children():
            tv_rep.delete(iid)
        for it in g.get("replacements") or []:
            if isinstance(it, dict):
                tv_rep.insert("", tk.END, values=(it.get("from", ""), it.get("to", "")))

    def _add_rep() -> None:
        frm = rf_from.get().strip()
        to = rf_to.get().strip()
        if not frm or not to:
            return
        reps = list(g.get("replacements") or [])
        reps.append({"from": frm, "to": to})
        g["replacements"] = reps
        _refresh_rep_tree()
        rf_from.delete(0, tk.END)
        rf_to.delete(0, tk.END)
        _update_preview()

    def _del_rep() -> None:
        sel = tv_rep.selection()
        if not sel:
            return
        vals = tv_rep.item(sel[0], "values")
        if len(vals) < 2:
            return
        frm, to = str(vals[0]), str(vals[1])
        reps = [x for x in (g.get("replacements") or []) if not (x.get("from") == frm and x.get("to") == to)]
        g["replacements"] = reps
        _refresh_rep_tree()
        _update_preview()

    rbf = ttk.Frame(rep_card)
    rbf.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    ttk.Button(rbf, text="Добавить замену", command=_add_rep).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(rbf, text="Удалить выбранную", command=_del_rep).pack(side=tk.LEFT)

    # ——— Контекст ———
    tab_ctx = ttk.Frame(nb, padding=12)
    nb.add(tab_ctx, text="  Контекст  ")

    ctx_card = ttk.LabelFrame(tab_ctx, text=" Общая подсказка для модели ", padding=10)
    ctx_card.pack(fill=tk.BOTH, expand=True)
    ttk.Label(
        ctx_card,
        text="Один-два предложения: тема разговора, жаргон, имена. Учитывается вместе с терминами.",
        style="Muted.TLabel",
        wraplength=640,
    ).pack(anchor=tk.W, pady=(0, 8))
    txt_ctx = tk.Text(ctx_card, height=12, wrap=tk.WORD, font=("SF Pro Text", 12), relief=tk.FLAT, padx=10, pady=10)
    txt_ctx.pack(fill=tk.BOTH, expand=True)
    txt_ctx.insert("1.0", str(g.get("context_hint") or ""))

    preview_frame = ttk.LabelFrame(outer, text=" Как сейчас выглядит подсказка для Whisper ", padding=10)
    preview_frame.pack(fill=tk.X, pady=(0, 8))
    preview_var = tk.StringVar(value="")
    prev_lbl = ttk.Label(preview_frame, textvariable=preview_var, style="Muted.TLabel", wraplength=660, justify=tk.LEFT)
    prev_lbl.pack(anchor=tk.W)

    def _update_preview() -> None:
        tmp = json.loads(json.dumps(data))
        tmp.setdefault("global", {})
        tmp["global"]["terms"] = g.get("terms", [])
        tmp["global"]["replacements"] = g.get("replacements", [])
        tmp["global"]["context_hint"] = txt_ctx.get("1.0", "end-1c")
        try:
            p = build_initial_prompt(preview_app_name, vocab=tmp)
            preview_var.set(p or "(пусто — термины не заданы)")
        except Exception as e:
            preview_var.set(f"(ошибка предпросмотра: {e})")

    def _on_any_change(*_a) -> None:
        g["context_hint"] = txt_ctx.get("1.0", "end-1c")
        _update_preview()

    txt_ctx.bind("<<Modified>>", lambda e: (_on_any_change(), txt_ctx.edit_modified(False)))
    txt_ctx.bind("<KeyRelease>", _on_any_change)

    def _refresh_all_lists() -> None:
        _refresh_terms_tree()
        _refresh_rep_tree()
        _update_preview()

    _refresh_all_lists()

    bottom = ttk.Frame(outer)
    bottom.pack(fill=tk.X)

    def _save() -> None:
        g["context_hint"] = txt_ctx.get("1.0", "end-1c").strip()
        full = load_vocab(force=True)
        full["global"] = g
        save_vocab(full)
        win.destroy()

    def _cancel() -> None:
        win.destroy()

    def _open_json() -> None:
        path = vocab_file_path()
        subprocess.run(["open", "-e", path], check=False)

    ttk.Button(bottom, text="Отмена", command=_cancel).pack(side=tk.RIGHT, padx=(8, 0))
    ttk.Button(bottom, text="Сохранить", command=_save).pack(side=tk.RIGHT)
    ttk.Button(bottom, text="Открыть vocab.json…", command=_open_json).pack(side=tk.LEFT)

    win.protocol("WM_DELETE_WINDOW", _cancel)
    win.update_idletasks()
    win.grab_set()
    try:
        win.lift()
        win.focus_force()
    except tk.TclError:
        pass
    root.wait_window(win)
