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
import tempfile
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

try:
    from whisper_version import get_version as _get_app_version
except ImportError:
    def _get_app_version() -> str:
        return "0.0.0-dev"

try:
    from whisper_file_log import log_dir as _whisper_server_log_dir
except ImportError:
    def _whisper_server_log_dir() -> Path:
        return ROOT


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


GUI_PREFS_PATH = ROOT / "whisper_gui_prefs.json"


def _load_gui_prefs() -> dict:
    try:
        return json.loads(GUI_PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_gui_prefs(data: dict) -> None:
    try:
        GUI_PREFS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _maybe_check_updates_gui(root: object, current_ver: str) -> None:
    import threading
    import tempfile
    import urllib.request
    import webbrowser
    from tkinter import messagebox

    try:
        from whisper_update_check import fetch_latest_release, is_remote_newer, pick_asset_url
    except ImportError:
        return

    def worker() -> None:
        if os.environ.get("WHISPER_SKIP_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes"):
            return
        rel = fetch_latest_release()
        if not rel:
            return
        tag = (rel.get("tag_name") or "").strip()
        if not is_remote_newer(tag, current_ver):
            return
        html = (rel.get("html_url") or "").strip() or "https://github.com/zapnikita95/whisper/releases"

        def ask() -> None:
            if not messagebox.askyesno(
                "Обновление Whisper Server",
                f"Доступна версия {tag} (у тебя {current_ver}).\n\nСкачать установщик?",
            ):
                return
            picked = pick_asset_url(rel, suffix=".exe", contains="whispersetup")
            if not picked:
                webbrowser.open(html)
                return
            name, url = picked
            try:
                fd, tmp = tempfile.mkstemp(suffix=".exe")
                os.close(fd)
                req = urllib.request.Request(url, headers={"User-Agent": "WhisperServerGUI/1.0"})
                with urllib.request.urlopen(req, timeout=600) as resp:
                    Path(tmp).write_bytes(resp.read())
                os.startfile(tmp)  # type: ignore[attr-defined]
            except OSError:
                webbrowser.open(html)

        try:
            root.after(0, ask)
        except Exception:
            pass

    threading.Thread(target=worker, name="whisper-update-check", daemon=True).start()


# Короткий таймаут: иначе на главном потоке Tk окно «Не отвечает» на секунды.
_HTTP_TIMEOUT_SEC = 1.0

# Опрос GET / после «Запустить сервер»: интервал и сколько ждать, пока импортируется faster_whisper/CUDA.
# Раньше было 240×250 мс ≈ 60 с — на реальных ПК импорт легко 2–5+ мин, GUI ошибочно показывал «нет ответа».
_API_START_POLL_MS = 250
_API_START_POLL_MAX_FAILS = 1200  # ×250 мс ≈ 5 мин между попытками + первый опрос через 300 мс


def _fetch_clients_json(port: int) -> dict | None:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/clients")
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError, TimeoutError):
        return None


def _fetch_root_json(port: int) -> dict | None:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/")
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError, TimeoutError):
        return None


# Uvicorn по умолчанию пишет в stderr; в --windowed exe это иногда блокирует поток → HTTP не поднимается.
# Структура как у uvicorn (нужны formatters), но handlers = NullHandler.
_UVICORN_GUI_LOG_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": False,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            "use_colors": False,
        },
    },
    "handlers": {
        "default": {"formatter": "default", "class": "logging.NullHandler"},
        "access": {"formatter": "access", "class": "logging.NullHandler"},
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}


def _run_uvicorn(port: int, host: str) -> None:
    import asyncio
    import logging
    import sys

    import uvicorn

    if sys.platform == "win32":
        # Proactor + uvicorn во вторичном потоке (Tk) часто не доходят до bind; Selector стабильнее.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    log = logging.getLogger("whisper.server")
    log.info("GUI: импорт whisper_server.app (уже может быть в кэше модулей)…")
    from whisper_server import app

    log.info("GUI: uvicorn.run host=%s port=%s (loop=asyncio, логи uvicorn → Null)", host, port)
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
            loop="asyncio",
            use_colors=False,
            log_config=_UVICORN_GUI_LOG_CONFIG,
        )
    except OSError:
        logging.getLogger("whisper.server").exception(
            "GUI: uvicorn OSError — часто порт уже занят другим процессом"
        )
    except Exception:
        logging.getLogger("whisper.server").exception("GUI: uvicorn.run завершился с ошибкой")
        raise


def _build_server_main_form(root: object, port: int, ts_ip: str, prefs: dict, app_ver: str) -> None:
    import tkinter as tk
    from tkinter import ttk, scrolledtext

    from whisper_models import MODEL_PRESETS

    server_diag_log = Path(tempfile.gettempdir()) / "WhisperServer_last_run.log"
    saved_key = str(prefs.get("model_key", "large-v3")).strip() or "large-v3"
    preset_keys = [k for k, _, _ in MODEL_PRESETS]
    if saved_key not in preset_keys:
        saved_key = "large-v3"
    label_by_key = {k: lbl for k, _, lbl in MODEL_PRESETS}

    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True)

    tab_server = ttk.Frame(nb, padding=12)
    tab_logs = ttk.Frame(nb, padding=8)
    nb.add(tab_server, text="Сервер")
    nb.add(tab_logs, text="Логи")

    frm = ttk.Frame(tab_server)
    frm.pack(fill=tk.BOTH, expand=True)

    # ——— вкладка «Логи»: хвост файла в реальном времени ———
    _log_tail_bytes = 120_000
    _log_max_lines = 8000
    _log_state: dict = {"which": "main", "offset": 0, "path": ""}

    def _log_path_main() -> Path:
        return _whisper_server_log_dir() / "whisper_server.log"

    def _log_path_temp() -> Path:
        return Path(tempfile.gettempdir()) / "WhisperServer_last_run.log"

    def _active_log_path() -> Path:
        return _log_path_main() if _log_state["which"] == "main" else _log_path_temp()

    log_src_var = tk.StringVar(value="Основной (whisper_server.log)")

    log_top = ttk.Frame(tab_logs)
    log_top.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(log_top, text="Файл:").pack(side=tk.LEFT, padx=(0, 6))
    cb_log = ttk.Combobox(
        log_top,
        textvariable=log_src_var,
        values=(
            "Основной (whisper_server.log)",
            f"Копия в TEMP ({server_diag_log.name})",
        ),
        state="readonly",
        width=42,
    )
    cb_log.pack(side=tk.LEFT, padx=(0, 8))

    autoscroll_var = tk.BooleanVar(value=True)

    def _open_log_in_explorer() -> None:
        p = _active_log_path()
        try:
            if p.is_file():
                subprocess.run(["explorer", "/select,", str(p.resolve())], check=False)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["explorer", str(p.parent.resolve())], check=False)
        except OSError:
            pass

    ttk.Button(log_top, text="Папка с файлом", command=_open_log_in_explorer).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Checkbutton(log_top, text="Автопрокрутка", variable=autoscroll_var).pack(side=tk.LEFT, padx=(0, 8))

    path_lbl_var = tk.StringVar(value="")
    ttk.Label(tab_logs, textvariable=path_lbl_var, font=("", 8), foreground="#555", wraplength=640).pack(
        anchor=tk.W, pady=(0, 4)
    )

    log_text = scrolledtext.ScrolledText(
        tab_logs,
        wrap=tk.NONE,
        font=("Consolas", 9),
        height=22,
        state=tk.NORMAL,
        bg="#1e1e1e",
        fg="#d4d4d4",
        insertbackground="#d4d4d4",
        selectbackground="#264f78",
    )
    log_text.pack(fill=tk.BOTH, expand=True)

    def _log_key_readonly(e: tk.Event) -> str | None:
        """Текст только для чтения, но выделение и Ctrl+C / Ctrl+A работают."""
        ks = e.keysym
        ctrl = (e.state & 0x4) != 0
        shift = (e.state & 0x1) != 0
        if ctrl and ks.lower() in ("c", "a", "insert"):
            return None
        if ctrl and ks.lower() in ("v", "x"):
            return "break"
        nav = (
            "Left",
            "Right",
            "Up",
            "Down",
            "Home",
            "End",
            "Next",
            "Prior",
            "KP_Left",
            "KP_Right",
            "KP_Up",
            "KP_Down",
        )
        if ks in nav or (shift and ks in nav):
            return None
        if ks in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Win_L", "Win_R"):
            return None
        return "break"

    log_text.bind("<Key>", _log_key_readonly)

    def _log_select_all(e: tk.Event | None = None) -> str | None:
        log_text.tag_add(tk.SEL, "1.0", tk.END)
        log_text.mark_set(tk.INSERT, tk.END)
        log_text.see(tk.INSERT)
        return "break" if e is not None else None

    log_text.bind("<Control-a>", _log_select_all)
    log_text.bind("<Control-A>", _log_select_all)

    def _copy_log_clipboard(text: str) -> None:
        if not text:
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update_idletasks()

    def _copy_log_selection() -> None:
        try:
            if log_text.tag_ranges(tk.SEL):
                _copy_log_clipboard(log_text.get(tk.SEL_FIRST, tk.SEL_LAST))
        except tk.TclError:
            pass

    def _copy_log_all() -> None:
        _copy_log_clipboard(log_text.get("1.0", "end-1c"))

    def _log_context_menu(e: tk.Event) -> None:
        m = tk.Menu(root, tearoff=0)
        m.add_command(label="Копировать", command=_copy_log_selection)
        m.add_command(label="Копировать всё", command=_copy_log_all)
        m.add_separator()
        m.add_command(label="Выделить всё", command=lambda: _log_select_all(None))
        m.tk_popup(e.x_root, e.y_root)

    log_text.bind("<Button-3>", _log_context_menu)

    def _clear_log_view() -> None:
        log_text.delete("1.0", tk.END)

    ttk.Button(log_top, text="Очистить окно", command=_clear_log_view).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(log_top, text="Копировать выделение", command=_copy_log_selection).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(log_top, text="Копировать всё", command=_copy_log_all).pack(side=tk.LEFT, padx=(6, 0))

    def _on_log_source_change(_evt: object | None = None) -> None:
        v = log_src_var.get()
        _log_state["which"] = "main" if "Основной" in v else "temp"
        _log_state["offset"] = 0
        _log_state["path"] = ""
        _clear_log_view()
        _pull_log_lines(initial=True)

    cb_log.bind("<<ComboboxSelected>>", _on_log_source_change)

    def _trim_log_widget() -> None:
        try:
            end_line = int(log_text.index("end-1c").split(".")[0])
        except (ValueError, tk.TclError):
            return
        if end_line > _log_max_lines:
            cut = end_line - _log_max_lines + 500
            log_text.delete("1.0", f"{cut}.0")

    def _append_log_chunk(chunk: str) -> None:
        if not chunk:
            return
        log_text.insert(tk.END, chunk)
        _trim_log_widget()
        if autoscroll_var.get():
            log_text.see(tk.END)

    def _pull_log_lines(*, initial: bool = False) -> None:
        path = _active_log_path()
        path_lbl_var.set(str(path.resolve()))
        try:
            if not path.is_file():
                if initial:
                    _append_log_chunk(
                        f"(Файл ещё не создан — появится после «Запустить сервер». Ожидаемый путь:\n{path}\n)\n"
                    )
                return
            size = path.stat().st_size
        except OSError:
            return

        key = str(path.resolve())
        if _log_state["path"] != key:
            _log_state["path"] = key
            _log_state["offset"] = 0

        prev_off = _log_state["offset"]
        if initial or size < prev_off:
            if (not initial) and size < prev_off:
                log_text.delete("1.0", tk.END)
            start = 0 if size <= _log_tail_bytes else size - _log_tail_bytes
            _log_state["offset"] = start
            if start > 0 and initial:
                prefix = f"… (показан хвост файла, ~{_log_tail_bytes // 1024} КБ) …\n"
            else:
                prefix = ""
        else:
            prefix = ""

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(_log_state["offset"])
                chunk = f.read()
                _log_state["offset"] = f.tell()
        except OSError:
            return

        if prefix:
            log_text.delete("1.0", tk.END)
            _append_log_chunk(prefix)
        if chunk:
            _append_log_chunk(chunk)

    def _schedule_log_poll() -> None:
        try:
            on_logs = nb.tab(nb.select(), "text") == "Логи"
        except tk.TclError:
            root.after(700, _schedule_log_poll)
            return
        if on_logs:
            _pull_log_lines(initial=False)
        root.after(700, _schedule_log_poll)

    root.after(400, lambda: _pull_log_lines(initial=True))
    root.after(500, _schedule_log_poll)

    ttk.Label(frm, text="Модель (faster-whisper)", font=("", 12, "bold")).pack(anchor=tk.W)
    model_var = tk.StringVar(value=label_by_key[saved_key])
    combo_models = ttk.Combobox(
        frm,
        textvariable=model_var,
        values=[lbl for _, _, lbl in MODEL_PRESETS],
        state="readonly",
        width=64,
    )
    combo_models.pack(anchor=tk.W, pady=(4, 2))
    try:
        combo_models.current(preset_keys.index(saved_key))
    except (ValueError, tk.TclError):
        pass
    ttk.Label(
        frm,
        text="Сначала выбери модель, затем «Запустить сервер». Сменить модель можно только после перезапуска этого окна.",
        font=("", 9),
        foreground="#444",
    ).pack(anchor=tk.W, pady=(0, 6))

    def _model_key_from_ui() -> str:
        cur = model_var.get()
        for k, _, lbl in MODEL_PRESETS:
            if lbl == cur:
                return k
        return "large-v3"

    srv_started = {"ok": False}
    poll_gen = {"n": 0}
    poll_worker_busy = {"v": False}
    tree_worker_busy = {"v": False}

    api_health_var = tk.StringVar(value="● API: жми «Запустить сервер»")
    api_health = ttk.Label(frm, textvariable=api_health_var, font=("Segoe UI", 10, "bold"))

    def _apply_api_health(data: dict | None, offline_reason: str | None = None) -> None:
        if data and data.get("status") == "ok":
            m = data.get("model") or "?"
            rd = "да" if data.get("ready") else "нет"
            api_health_var.set(f"● API онлайн · модель: {m} · веса загружены: {rd}")
            api_health.configure(foreground="#0a6")
        elif offline_reason:
            api_health_var.set(f"● API недоступен ({offline_reason})")
            api_health.configure(foreground="#a30")
        else:
            api_health_var.set("● API: нет ответа")
            api_health.configure(foreground="#a30")

    def _schedule_api_poll() -> None:
        """Опрос GET / только в фоне — иначе Tk зависает (Not Responding)."""
        if not srv_started["ok"] or poll_worker_busy["v"]:
            return
        poll_worker_busy["v"] = True

        def work() -> None:
            data: dict | None = None
            try:
                data = _fetch_root_json(port)
            finally:

                def apply() -> None:
                    poll_worker_busy["v"] = False
                    if not srv_started["ok"]:
                        return
                    if data and data.get("status") == "ok":
                        _apply_api_health(data)
                        status.config(
                            text="Сервер отвечает. Закрой окно — остановка (процесс завершится).",
                            foreground="#0a0",
                        )
                        return
                    poll_gen["n"] = poll_gen.get("n", 0) + 1
                    if poll_gen["n"] > _API_START_POLL_MAX_FAILS:
                        _apply_api_health(
                            None,
                            f"таймаут ~{(_API_START_POLL_MAX_FAILS * _API_START_POLL_MS) // 60_000} мин",
                        )
                        status.config(
                            text=f"Сервер не поднялся — см. whisper_server.log и {server_diag_log}",
                            foreground="#a00",
                        )
                        return
                    sec = poll_gen["n"] // 4
                    api_health_var.set(f"● Запуск API… (~{sec} с) — окно не зависло, ждём в фоне")
                    api_health.configure(foreground="#c80")
                    root.after(_API_START_POLL_MS, _schedule_api_poll)

                root.after(0, apply)

        threading.Thread(target=work, name="whisper-gui-poll", daemon=True).start()

    def on_start_server() -> None:
        if srv_started["ok"]:
            return
        srv_started["ok"] = True
        poll_gen["n"] = 0
        key = _model_key_from_ui()
        _save_gui_prefs({"model_key": key})
        os.environ["WHISPER_MODEL"] = key
        api_health_var.set(
            "● Запуск uvicorn… (импорт CUDA/CT2 часто 1–5 мин — GUI ждёт до ~5 мин, см. лог)"
        )
        api_health.configure(foreground="#c80")
        threading.Thread(
            target=lambda: _run_uvicorn(port, "0.0.0.0"),
            name="uvicorn",
            daemon=True,
        ).start()
        combo_models.configure(state="disabled")
        start_btn.state(["disabled"])
        status.config(
            text=f"Сервер грузится в фоне — лог: whisper_server.log и {server_diag_log}",
            foreground="#666",
        )
        root.after(300, _schedule_api_poll)

    start_btn = ttk.Button(frm, text="Запустить сервер", command=on_start_server)
    start_btn.pack(anchor=tk.W, pady=(4, 8))

    ttk.Label(frm, text="HTTP API (удалённые клиенты)", font=("", 12, "bold")).pack(anchor=tk.W)
    api_health.pack(anchor=tk.W, pady=(2, 0))

    ttk.Label(frm, text=f"Порт: {port}   •   Локально: http://127.0.0.1:{port}/").pack(anchor=tk.W, pady=(4, 0))

    lan_line = f"В сети (0.0.0.0:{port}) — подключай Mac / другие ПК по IP этого компьютера."
    if ts_ip:
        lan_line += f"\nTailscale IPv4: {ts_ip}  →  URL для Mac: http://{ts_ip}:{port}/"
    ttk.Label(frm, text=lan_line, wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 12))

    ttk.Label(frm, text="Запись голоса на этом ПК (Windows)", font=("", 12, "bold")).pack(anchor=tk.W)
    hotkey_txt = (
        "Запись на этом ПК (Ctrl+Win) — Whisper Hotkey (трей, уведомления):\n"
        "WhisperHotkey.exe или start-whisper-hotkey-gui.bat. Лог: whisper_hotkey.log.\n"
        "Это не HTTP: клавиши локально; сервер выше — для Mac и других машин по сети."
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

    status = ttk.Label(
        frm,
        text="Выбери модель и нажми «Запустить сервер».",
        foreground="#666",
    )
    status.pack(anchor=tk.W)

    def refresh_tree() -> None:
        if tree_worker_busy["v"]:
            root.after(1500, refresh_tree)
            return
        tree_worker_busy["v"] = True

        def work() -> None:
            root_data = None
            clients_data = None
            try:
                if srv_started["ok"]:
                    root_data = _fetch_root_json(port)
                clients_data = _fetch_clients_json(port)
            finally:

                def apply() -> None:
                    tree_worker_busy["v"] = False
                    if srv_started["ok"]:
                        if root_data and root_data.get("status") == "ok":
                            _apply_api_health(root_data)
                        elif poll_gen["n"] > _API_START_POLL_MAX_FAILS:
                            _apply_api_health(None, "нет ответа")
                    for i in tree.get_children():
                        tree.delete(i)
                    if clients_data:
                        for row in clients_data.get("clients", []):
                            tree.insert(
                                "",
                                tk.END,
                                values=(
                                    row.get("ip", ""),
                                    row.get("client", ""),
                                    row.get("last_seen_ago_sec", ""),
                                ),
                            )
                    root.after(1500, refresh_tree)

                root.after(0, apply)

        threading.Thread(target=work, name="whisper-gui-clients", daemon=True).start()

    refresh_tree()

    root.after(10_000, lambda: _maybe_check_updates_gui(root, app_ver))

    def on_close() -> None:
        status.config(text="Остановка…", foreground="#a00")
        root.update_idletasks()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)


def main() -> int:
    import tkinter as tk
    from tkinter import ttk, messagebox

    prefs = _load_gui_prefs()
    app_ver = _get_app_version()
    root = tk.Tk()
    root.title(f"Whisper GPU Server  v{app_ver}")
    root.geometry("520x160")
    root.minsize(400, 120)

    boot_frm = ttk.Frame(root, padding=24)
    boot_frm.pack(fill=tk.BOTH, expand=True)
    ttk.Label(
        boot_frm,
        text="Подготовка: свободный порт и брандмауэр (PowerShell/netsh могут занять до ~1 мин).\nОкно уже живое — его можно двигать.",
        wraplength=480,
        justify=tk.LEFT,
    ).pack(anchor=tk.W)
    boot_status = ttk.Label(boot_frm, text="Старт…", foreground="#444")
    boot_status.pack(anchor=tk.W, pady=(12, 0))
    boot_state: dict = {}

    def apply_boot_result() -> None:
        try:
            if not root.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            boot_frm.destroy()
        except tk.TclError:
            return
        err = boot_state.get("error")
        if err:
            messagebox.showerror("Whisper Server", str(err))
            root.destroy()
            return
        root.geometry("600x520")
        root.minsize(520, 440)
        _build_server_main_form(
            root,
            int(boot_state["port"]),
            str(boot_state.get("ts_ip") or ""),
            prefs,
            app_ver,
        )

    def boot_worker() -> None:
        def upd(msg: str) -> None:
            def u() -> None:
                try:
                    if boot_frm.winfo_exists():
                        boot_status.config(text=msg)
                except tk.TclError:
                    pass

            try:
                root.after(0, u)
            except Exception:
                pass

        try:
            upd("Свободный порт…")
            p = _find_free_port()
            upd(f"Порт {p}. Правило брандмауэра…")
            _firewall_allow(p)
            _write_port_file(p)
            upd("Tailscale…")
            ts = _tailscale_ipv4()
            boot_state.clear()
            boot_state.update(port=p, ts_ip=ts)
        except Exception as e:
            boot_state.clear()
            boot_state["error"] = str(e)
        try:
            root.after(0, apply_boot_result)
        except tk.TclError:
            pass

    threading.Thread(target=boot_worker, name="whisper-gui-boot", daemon=True).start()
    root.mainloop()
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
