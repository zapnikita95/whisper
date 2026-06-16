#!/usr/bin/env python3
"""
Whisper GPU Server window (Windows): port, Ctrl+Win hint, HTTP clients, model library.
Run without console: build exe via PyInstaller (see packaging/build-server-gui-exe.bat).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform != "win32":
    print("whisper_server_gui.py is for Windows.", file=sys.stderr)
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


def _server_window_ico_path() -> Path | None:
    """Иконка окна (в exe — из _internal/assets)."""
    if getattr(sys, "frozen", False):
        meip = getattr(sys, "_MEIPASS", None)
        if meip:
            for name in ("app_icon.ico", "server_icon.ico"):
                p = Path(meip) / "assets" / name
                if p.is_file():
                    return p
    for name in ("app_icon.ico", "server_icon.ico"):
        p = ROOT / "assets" / name
        if p.is_file():
            return p
    p = ROOT / "assets" / "app_icon.ico"
    return p if p.is_file() else None

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


_HTTP_TIMEOUT_SEC = 1.0


def _fetch_root_json(port: int, *, timeout: float | None = None) -> dict | None:
    tmo = _HTTP_TIMEOUT_SEC if timeout is None else timeout
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/")
        with urllib.request.urlopen(req, timeout=tmo) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError, TimeoutError):
        return None


def _whisper_api_at(port: int) -> dict | None:
    data = _fetch_root_json(port, timeout=0.5)
    if _is_whisper_server_api(data):
        return data
    return None


def _is_whisper_server_api(data: dict | None) -> bool:
    if not data or data.get("status") != "ok":
        return False
    return "app_version" in data and "windows_local_hotkey" in data


def _pids_listening_on_port(port: int) -> list[int]:
    try:
        r = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    needle = f":{port}"
    out: set[int] = set()
    for line in (r.stdout or "").splitlines():
        if "LISTENING" not in line or needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        pid_s = parts[-1]
        if pid_s.isdigit():
            out.add(int(pid_s))
    return sorted(out)


def _pid_process_name(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    line = (r.stdout or "").strip()
    if not line or "No tasks" in line:
        return ""
    return line.split(",")[0].strip().strip('"')


def _pid_is_whisper_server(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    name = _pid_process_name(pid).lower()
    if name == "whisperserver.exe":
        return True
    if name not in ("python.exe", "pythonw.exe"):
        return False
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        cmd = (r.stdout or "").lower()
        return "whisper_server" in cmd
    except (OSError, subprocess.TimeoutExpired):
        return False


def _port_occupied_by_whisper_server(port: int) -> bool:
    if _whisper_api_at(port):
        return True
    return any(_pid_is_whisper_server(pid) for pid in _pids_listening_on_port(port))


def _reclaim_port_from_old_whisper(port: int, *, wait_sec: float = 6.0) -> tuple[bool, str | None]:
    """Завершить старый Whisper Server на порту. Не трогает чужие процессы."""
    if not _port_occupied_by_whisper_server(port):
        return False, None
    pids = [p for p in _pids_listening_on_port(port) if _pid_is_whisper_server(p)]
    if not pids and _whisper_api_at(port):
        pids = [
            p
            for p in _pids_listening_on_port(port)
            if _pid_process_name(p).lower() == "whisperserver.exe" and p != os.getpid()
        ]
    if not pids:
        return False, f"На порту {port} отвечает Whisper API, но процесс не найден."
    killed: list[int] = []
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        killed.append(pid)
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        if _port_is_available(port):
            who = ", ".join(str(p) for p in killed)
            return True, f"Остановлен старый Whisper Server (PID {who}) — порт {port} свободен."
        time.sleep(0.2)
    return False, f"Не удалось освободить порт {port} после остановки старого сервера."


def _find_free_port(start: int = 8000, end: int = 8100) -> int:
    for p in range(start, end):
        if _port_is_available(p):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return int(s.getsockname()[1])


def _port_has_listener(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _port_is_available(port: int) -> bool:
    if not (1024 <= port <= 65535):
        return False
    if _port_has_listener(port):
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", port))
    except OSError:
        return False
    return True


def _pick_listen_port(prefs: dict, *, preferred_first: int | None = None) -> tuple[int, str | None]:
    """
    Стабильный порт: server_port.txt / last_listen_port, если свободен.
    Старый Whisper Server на порту — завершить и занять тот же порт.
    Чужое приложение — следующий свободный порт + предупреждение.
    """
    sticky: list[int] = []
    if preferred_first is not None:
        sticky.append(int(preferred_first))
    try:
        pf = ROOT / "server_port.txt"
        if pf.is_file():
            sticky.append(int(pf.read_text().strip()))
    except (ValueError, OSError):
        pass
    lp = prefs.get("last_listen_port")
    if isinstance(lp, int) and lp not in sticky:
        sticky.append(lp)
    if not sticky:
        sticky.extend([8001, 8000])
    seen: set[int] = set()
    ordered: list[int] = []
    for p in sticky:
        if p not in seen:
            seen.add(p)
            ordered.append(p)

    foreign_on: int | None = None
    for want in ordered:
        if not (1024 <= want <= 65535):
            continue
        if _port_is_available(want):
            return want, None
        if _port_occupied_by_whisper_server(want):
            ok, note = _reclaim_port_from_old_whisper(want)
            if ok and _port_is_available(want):
                return want, note
            continue
        if foreign_on is None:
            foreign_on = want

    fb = _find_free_port()
    if foreign_on is not None:
        return (
            fb,
            f"Порт {foreign_on} занят другим приложением — Whisper Server слушает {fb}. Обнови URL на Mac.",
        )
    if ordered:
        return (
            fb,
            f"Порт {ordered[0]} занят — сервер слушает {fb}. Обнови URL на Mac и в hotkey (Tailscale / IP).",
        )
    return fb, None


def _reserve_listen_port(prefs: dict, preferred: int | None = None) -> tuple[int, str | None]:
    """Перед uvicorn: освободить порт от старого Whisper или выбрать другой."""
    return _pick_listen_port(prefs, preferred_first=preferred)


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
                "Whisper Server update",
                f"Version {tag} is available (you have {current_ver}).\n\nDownload installer?",
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


def _run_uvicorn(port: int, host: str, err_holder: dict | None = None) -> None:
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
    except OSError as e:
        msg = f"Порт {port} занят или недоступен: {e}"
        logging.getLogger("whisper.server").exception("GUI: uvicorn OSError — %s", msg)
        if err_holder is not None:
            err_holder["err"] = msg
    except Exception as e:
        logging.getLogger("whisper.server").exception("GUI: uvicorn.run завершился с ошибкой")
        if err_holder is not None:
            err_holder["err"] = str(e)
        raise


def _build_server_main_form(
    root: object,
    port: int,
    ts_ip: str,
    prefs: dict,
    app_ver: str,
    *,
    port_note: str | None = None,
) -> None:
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
    tab_models = ttk.Frame(nb, padding=4)
    tab_logs = ttk.Frame(nb, padding=8)
    nb.add(tab_server, text="Server")
    nb.add(tab_models, text="Models")
    nb.add(tab_logs, text="Logs")

    frm = ttk.Frame(tab_server)
    frm.pack(fill=tk.BOTH, expand=True)

    # ——— Logs tab: live tail ———
    _log_tail_bytes = 120_000
    _log_max_lines = 8000
    _log_state: dict = {"which": "main", "offset": 0, "path": ""}

    def _log_path_main() -> Path:
        return _whisper_server_log_dir() / "whisper_server.log"

    def _log_path_temp() -> Path:
        return Path(tempfile.gettempdir()) / "WhisperServer_last_run.log"

    def _active_log_path() -> Path:
        return _log_path_main() if _log_state["which"] == "main" else _log_path_temp()

    log_src_var = tk.StringVar(value="Main (whisper_server.log)")

    log_top = ttk.Frame(tab_logs)
    log_top.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(log_top, text="File:").pack(side=tk.LEFT, padx=(0, 6))
    cb_log = ttk.Combobox(
        log_top,
        textvariable=log_src_var,
        values=(
            "Main (whisper_server.log)",
            f"TEMP copy ({server_diag_log.name})",
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

    ttk.Button(log_top, text="Open folder", command=_open_log_in_explorer).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Checkbutton(log_top, text="Auto-scroll", variable=autoscroll_var).pack(side=tk.LEFT, padx=(0, 8))

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
        m.add_command(label="Copy", command=_copy_log_selection)
        m.add_command(label="Copy all", command=_copy_log_all)
        m.add_separator()
        m.add_command(label="Select all", command=lambda: _log_select_all(None))
        m.tk_popup(e.x_root, e.y_root)

    log_text.bind("<Button-3>", _log_context_menu)

    def _clear_log_view() -> None:
        log_text.delete("1.0", tk.END)

    ttk.Button(log_top, text="Clear view", command=_clear_log_view).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(log_top, text="Copy selection", command=_copy_log_selection).pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(log_top, text="Copy all", command=_copy_log_all).pack(side=tk.LEFT, padx=(6, 0))

    def _on_log_source_change(_evt: object | None = None) -> None:
        v = log_src_var.get()
        _log_state["which"] = "main" if "Main" in v else "temp"
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
                        f"(File not created yet — appears after Start server. Expected path:\n{path}\n)\n"
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
                prefix = f"… (showing tail ~{_log_tail_bytes // 1024} KB) …\n"
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
            on_logs = nb.tab(nb.select(), "text") == "Logs"
        except tk.TclError:
            root.after(700, _schedule_log_poll)
            return
        if on_logs:
            _pull_log_lines(initial=False)
        root.after(700, _schedule_log_poll)

    root.after(400, lambda: _pull_log_lines(initial=True))
    root.after(500, _schedule_log_poll)

    ttk.Label(frm, text="Model (faster-whisper)", font=("", 12, "bold")).pack(anchor=tk.W)
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
        text="Pick a model, then Start server. To change model after start, restart this window. See Models tab for downloads.",
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
    active_port = {"value": port}
    port_note_state = {"text": port_note or ""}

    def _pick_model_from_library(key: str) -> None:
        if key not in label_by_key:
            return
        model_var.set(label_by_key[key])
        try:
            combo_models.current(preset_keys.index(key))
        except (ValueError, tk.TclError):
            pass
        merged = dict(_load_gui_prefs())
        merged["model_key"] = key
        _save_gui_prefs(merged)

    from whisper_server_gui_models_tab import build_models_tab

    build_models_tab(tab_models, root, active_port, on_pick_model=_pick_model_from_library)

    def _current_port() -> int:
        return int(active_port["value"])

    api_health_var = tk.StringVar(value="● API: click Start server")
    api_health = ttk.Label(frm, textvariable=api_health_var, font=("Segoe UI", 10, "bold"))

    port_line_var = tk.StringVar(
        value=f"Port: {_current_port()}   •   Local: http://127.0.0.1:{_current_port()}/"
    )
    port_note_var = tk.StringVar(value=port_note_state["text"])
    lan_var = tk.StringVar(
        value=(
            f"Network (0.0.0.0:{_current_port()}) — connect Mac / other PCs using this machine's IP."
            + (f"\nTailscale IPv4: {ts_ip}  →  Mac URL: http://{ts_ip}:{_current_port()}/" if ts_ip else "")
        )
    )

    def _apply_port_change(new_port: int, note: str | None) -> None:
        active_port["value"] = new_port
        if note:
            port_note_state["text"] = note
            port_note_var.set(note)
        _write_port_file(new_port)
        merged = dict(_load_gui_prefs())
        merged["last_listen_port"] = new_port
        _save_gui_prefs(merged)
        _firewall_allow(new_port)
        port_line_var.set(f"Port: {new_port}   •   Local: http://127.0.0.1:{new_port}/")
        lan_var.set(
            f"Network (0.0.0.0:{new_port}) — connect Mac / other PCs using this machine's IP."
            + (f"\nTailscale IPv4: {ts_ip}  →  Mac URL: http://{ts_ip}:{new_port}/" if ts_ip else "")
        )

    def _apply_api_health(data: dict | None, offline_reason: str | None = None) -> None:
        if data and data.get("status") == "ok":
            m = data.get("model") or "?"
            rd = "yes" if data.get("ready") else "no"
            api_health_var.set(f"● API online · model: {m} · weights loaded: {rd}")
            api_health.configure(foreground="#0a6")
        elif offline_reason:
            api_health_var.set(f"● API offline ({offline_reason})")
            api_health.configure(foreground="#a30")
        else:
            api_health_var.set("● API: no response")
            api_health.configure(foreground="#a30")

    def _schedule_api_poll() -> None:
        """Опрос GET / только в фоне — иначе Tk зависает (Not Responding)."""
        if not srv_started["ok"] or poll_worker_busy["v"]:
            return
        poll_worker_busy["v"] = True

        def work() -> None:
            data: dict | None = None
            try:
                data = _fetch_root_json(_current_port())
            finally:

                def apply() -> None:
                    poll_worker_busy["v"] = False
                    if not srv_started["ok"]:
                        return
                    if data and data.get("status") == "ok":
                        _apply_api_health(data)
                        status.config(
                            text="Server is up. Close this window to stop (process will exit).",
                            foreground="#0a0",
                        )
                        return
                    poll_gen["n"] = poll_gen.get("n", 0) + 1
                    if poll_gen["n"] > _API_START_POLL_MAX_FAILS:
                        _apply_api_health(
                            None,
                            f"timeout ~{(_API_START_POLL_MAX_FAILS * _API_START_POLL_MS) // 60_000} min",
                        )
                        status.config(
                            text=f"Server did not start — see whisper_server.log and {server_diag_log}",
                            foreground="#a00",
                        )
                        return
                    sec = poll_gen["n"] // 4
                    api_health_var.set(f"● Starting API… (~{sec} s) — waiting in background")
                    api_health.configure(foreground="#c80")
                    root.after(_API_START_POLL_MS, _schedule_api_poll)

                root.after(0, apply)

        threading.Thread(target=work, name="whisper-gui-poll", daemon=True).start()

    def on_start_server() -> None:
        if srv_started["ok"]:
            return

        prefs_now = _load_gui_prefs()
        cur = _current_port()
        new_p, note = _reserve_listen_port(prefs_now, preferred=cur)
        if new_p != cur or note:
            _apply_port_change(new_p, note or port_note_state["text"])

        srv_started["ok"] = True
        poll_gen["n"] = 0
        key = _model_key_from_ui()
        _save_gui_prefs({"model_key": key})
        os.environ["WHISPER_MODEL"] = key
        api_health_var.set(
            "● Starting uvicorn… (CUDA/CT2 import often 1–5 min — GUI waits up to ~5 min, see log)"
        )
        api_health.configure(foreground="#c80")
        listen_port = _current_port()
        err_holder: dict = {}

        def run_uvicorn() -> None:
            _run_uvicorn(listen_port, "0.0.0.0", err_holder=err_holder)

        threading.Thread(target=run_uvicorn, name="uvicorn", daemon=True).start()
        combo_models.configure(state="disabled")
        start_btn.state(["disabled"])
        status.config(
            text=f"Server loading in background on port {listen_port} — log: whisper_server.log and {server_diag_log}",
            foreground="#666",
        )
        root.after(300, _schedule_api_poll)

        def watch_bind() -> None:
            if err_holder.get("err"):
                nxt, note2 = _reserve_listen_port(_load_gui_prefs(), preferred=_current_port())
                if nxt == _current_port() and not _port_is_available(nxt):
                    nxt = _find_free_port(max(_current_port() + 1, 8000))
                    note2 = f"Port {_current_port()} failed — auto-selected {nxt}."
                _apply_port_change(nxt, note2 or f"Port {_current_port()} failed — selected {nxt}.")
                err_holder.clear()
                srv_started["ok"] = False
                poll_gen["n"] = 0
                on_start_server()
                return
            if _whisper_api_at(_current_port()):
                return
            if poll_gen["n"] < 16:
                root.after(500, watch_bind)

        root.after(1500, watch_bind)

    start_btn = ttk.Button(frm, text="Start server", command=on_start_server)
    start_btn.pack(anchor=tk.W, pady=(4, 8))

    ttk.Label(frm, text="HTTP API (remote clients)", font=("", 12, "bold")).pack(anchor=tk.W)
    api_health.pack(anchor=tk.W, pady=(2, 0))

    ttk.Label(frm, textvariable=port_line_var).pack(anchor=tk.W, pady=(4, 0))
    ttk.Label(
        frm,
        textvariable=port_note_var,
        wraplength=540,
        justify=tk.LEFT,
        foreground="#a30",
        font=("", 9, "bold"),
    ).pack(anchor=tk.W, pady=(2, 0))

    ttk.Label(frm, textvariable=lan_var, wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 12))

    ttk.Label(frm, text="Local voice input (Windows)", font=("", 12, "bold")).pack(anchor=tk.W)
    hotkey_txt = (
        "Record on this PC (Ctrl+Win) — Whisper Hotkey (tray, notifications):\n"
        "WhisperHotkey.exe or start-whisper-hotkey-gui.bat. Log: whisper_hotkey.log.\n"
        "Not HTTP: hotkeys are local; the server above is for Mac and other machines on the network."
    )
    ttk.Label(frm, text=hotkey_txt, wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 12))

    ttk.Label(
        frm,
        text="Recent remote clients (GET / or POST /transcribe; not 127.0.0.1)",
        font=("", 12, "bold"),
    ).pack(anchor=tk.W)
    cols = ("ip", "client", "sec")
    tree = ttk.Treeview(frm, columns=cols, show="headings", height=8)
    tree.heading("ip", text="IP")
    tree.heading("client", text="Client (header)")
    tree.heading("sec", text="Sec ago")
    tree.column("ip", width=140)
    tree.column("client", width=120)
    tree.column("sec", width=80)
    tree.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

    status = ttk.Label(
        frm,
        text="Pick a model and click Start server.",
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
                    root_data = _fetch_root_json(_current_port())
                clients_data = _fetch_clients_json(_current_port())
            finally:

                def apply() -> None:
                    tree_worker_busy["v"] = False
                    if srv_started["ok"]:
                        if root_data and root_data.get("status") == "ok":
                            _apply_api_health(root_data)
                        elif poll_gen["n"] > _API_START_POLL_MAX_FAILS:
                            _apply_api_health(None, "no response")
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
        status.config(text="Stopping…", foreground="#a00")
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
    _ico = _server_window_ico_path()
    if _ico is not None:
        try:
            root.iconbitmap(default=str(_ico))
        except tk.TclError:
            pass

    boot_frm = ttk.Frame(root, padding=24)
    boot_frm.pack(fill=tk.BOTH, expand=True)
    ttk.Label(
        boot_frm,
        text="Preparing: free port and firewall rule (may take up to ~1 min).\nYou can move this window while waiting.",
        wraplength=480,
        justify=tk.LEFT,
    ).pack(anchor=tk.W)
    boot_status = ttk.Label(boot_frm, text="Starting…", foreground="#444")
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
        root.geometry("720x580")
        root.minsize(600, 480)
        _build_server_main_form(
            root,
            int(boot_state["port"]),
            str(boot_state.get("ts_ip") or ""),
            _load_gui_prefs(),
            app_ver,
            port_note=boot_state.get("port_note"),
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
            upd("Port (prefer saved)…")
            p, port_note = _pick_listen_port(prefs)
            merged = dict(prefs)
            merged["last_listen_port"] = p
            _save_gui_prefs(merged)
            upd(f"Port {p}. Firewall rule…")
            _firewall_allow(p)
            _write_port_file(p)
            upd("Tailscale…")
            ts = _tailscale_ipv4()
            boot_state.clear()
            boot_state.update(port=p, ts_ip=ts, port_note=port_note)
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
