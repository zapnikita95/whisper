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
    from tkinter import ttk

    from whisper_models import MODEL_PRESETS

    server_diag_log = Path(tempfile.gettempdir()) / "WhisperServer_last_run.log"
    saved_key = str(prefs.get("model_key", "large-v3")).strip() or "large-v3"
    preset_keys = [k for k, _, _ in MODEL_PRESETS]
    if saved_key not in preset_keys:
        saved_key = "large-v3"
    label_by_key = {k: lbl for k, _, lbl in MODEL_PRESETS}

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill=tk.BOTH, expand=True)

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
        root.geometry("560x460")
        root.minsize(480, 400)
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
