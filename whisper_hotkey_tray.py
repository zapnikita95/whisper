#!/usr/bin/env python3
"""
Whisper Hotkey в фоне: иконка в трее, уведомления (запуск / запись / результат / ошибки).
Лог: whisper_hotkey.log в каталоге данных пользователя (%LOCALAPPDATA%\\WhisperHotkey при установке в Program Files). Отключить уведомления: трей «Уведомления» или WHISPER_HOTKEY_NO_NOTIFICATIONS=1.
Groq: GROQ_API_KEY в .env или ключ в меню «Groq API ключ…» (whisper_hotkey_prefs.json); env важнее. «Транскрипция» — как на Mac (server = локальный GPU). WHISPER_TRANSCRIBE_BACKEND / WHISPER_MAC_TRANSCRIBE_BACKEND.
Голос (как на Mac): эталон в ~/.whisper/speaker_embedding.npy, меню «Записать эталон…», «Проверка голоса» или WHISPER_SPEAKER_VERIFY=1 (нужен pip install -r requirements-speaker.txt при сборке exe).
Без стартового тоста: WHISPER_HOTKEY_SILENT_START=1. Повторы одного и того же текста и частые тосты режутся (антиспам).

Сборка: packaging/build-hotkey-gui-exe.bat → WhisperHotkey.exe
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

if sys.platform != "win32":
    print("whisper_hotkey_tray.py только для Windows.", file=sys.stderr)
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
    from whisper_groq import load_whisper_dotenv_files

    load_whisper_dotenv_files()
except ImportError:
    pass

from whisper_file_log import user_data_dir
from whisper_groq import (
    ensure_hotkey_default_prefs,
    hotkey_prefs_path,
    load_hotkey_prefs,
    save_hotkey_prefs,
)

USER_DATA = user_data_dir("WhisperHotkey")
PREFS_PATH = hotkey_prefs_path()
OLD_PREFS = ROOT / "whisper_hotkey_gui_prefs.json"
LEGACY_PREFS = ROOT / "whisper_hotkey_prefs.json"


def _ensure_user_data_dir() -> None:
    try:
        USER_DATA.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _migrate_legacy_prefs() -> None:
    if PREFS_PATH.is_file():
        return
    candidates = [LEGACY_PREFS, OLD_PREFS]
    # dist\WhisperHotkey\whisper_hotkey_prefs.json если раньше писали рядом с exe
    for legacy in candidates:
        try:
            if legacy.is_file() and legacy.resolve() != PREFS_PATH.resolve():
                PREFS_PATH.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
                return
        except OSError:
            continue


_ensure_user_data_dir()
_migrate_legacy_prefs()
ensure_hotkey_default_prefs()


def _load_prefs() -> dict:
    data = load_hotkey_prefs()
    if data:
        return data
    try:
        if OLD_PREFS.is_file():
            legacy = json.loads(OLD_PREFS.read_text(encoding="utf-8"))
            merged = {
                "model_key": legacy.get("model_key", "large-v3"),
                "notifications": True,
                "speaker_verify": False,
                "paste_mode": "auto",
                "transcribe_backend": "auto_vram",
            }
            _save_prefs(merged)
            return merged
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return ensure_hotkey_default_prefs()


def _save_prefs(data: dict) -> None:
    _ensure_user_data_dir()
    save_hotkey_prefs(data)


def _notifications_enabled() -> bool:
    v = os.environ.get("WHISPER_HOTKEY_NO_NOTIFICATIONS", "").strip().lower()
    if v in ("1", "true", "yes"):
        return False
    return bool(_load_prefs().get("notifications", True))


_NOTIFY_LOCK = threading.Lock()
_NOTIFY_STATE: dict = {"t": 0.0, "sig": "", "title_t": {}}


def _notify(title: str, body: str, error: bool = False, *, force: bool = False) -> None:
    if not _notifications_enabled():
        return
    sig = f"{title}\x00{body[:160]}"
    now = time.monotonic()
    if not force:
        gap = 4.0 if error else 5.0
        if error and title in ("Timeout", "Transcription", "Model", "Network or disk"):
            gap = max(gap, 20.0)
        with _NOTIFY_LOCK:
            dup_win = 45.0 if error else 25.0
            if sig == _NOTIFY_STATE.get("sig") and now - float(_NOTIFY_STATE.get("t", 0)) < dup_win:
                return
            if now - float(_NOTIFY_STATE.get("t", 0)) < gap:
                return
            tt = _NOTIFY_STATE.setdefault("title_t", {})
            if isinstance(tt, dict):
                last_t = float(tt.get(title) or 0.0)
                title_gap = 30.0 if title in ("Timeout", "Transcription") else 12.0
                if error and last_t > 0.0 and now - last_t < title_gap:
                    return
                tt[title] = now
            _NOTIFY_STATE["sig"] = sig
            _NOTIFY_STATE["t"] = now
    else:
        with _NOTIFY_LOCK:
            _NOTIFY_STATE["sig"] = sig
            _NOTIFY_STATE["t"] = now
    try:
        from plyer import notification

        notification.notify(
            title=title[:63],
            message=body[:255],
            app_name="Whisper Hotkey",
            timeout=5,
        )
    except Exception:
        import logging

        logging.getLogger("whisper.hotkey").debug("toast failed", exc_info=True)


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _speaker_threshold_from_env() -> float | None:
    raw = os.environ.get("WHISPER_SPEAKER_THRESHOLD", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _speaker_threshold_from_prefs(hp: dict) -> float | None:
    v = hp.get("speaker_threshold")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    return _speaker_threshold_from_env()


def _run_enroll_speaker_worker(log, notify) -> None:
    """Запись ~45 с с микрофона → ~/.whisper/speaker_embedding.npy (как enroll на Mac)."""
    import tempfile

    import numpy as np
    import pyaudio
    import soundfile as sf

    sec = 45
    rate = 16000
    chunk = 1024
    n_chunks = int(rate / chunk * sec) + 1
    notify("Voice profile", f"Recording in 2 s for {sec} s — speak naturally.", False, force=True)
    time.sleep(2.0)
    stream = None
    pa = None
    path: str | None = None
    try:
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=1,
            rate=rate,
            input=True,
            frames_per_buffer=chunk,
        )
        parts: list[bytes] = []
        for _ in range(n_chunks):
            parts.append(stream.read(chunk, exception_on_overflow=False))
        raw_audio = b"".join(parts)
        audio = np.frombuffer(raw_audio, dtype=np.float32)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sf.write(path, audio, rate)
        from speaker_verify import enroll_from_wav

        enroll_from_wav(path)
        pr = _load_prefs()
        pr["speaker_verify"] = True
        _save_prefs(pr)
        notify(
            "Voice profile",
            "Saved. Voice verify enabled in settings — restart hotkey.",
            False,
            force=True,
        )
    except ImportError:
        log.exception("enroll: нет speaker_verify / torch")
        notify(
            "Voice profile",
            "Missing deps: pip install -r requirements-speaker.txt and rebuild exe.",
            True,
            force=True,
        )
    except OSError as e:
        log.exception("enroll: микрофон")
        notify("Voice profile", f"Microphone: {e}"[:220], True, force=True)
    except Exception as e:
        log.exception("enroll failed")
        notify("Voice profile", str(e)[:220], True, force=True)
    finally:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except OSError:
                pass
        if pa is not None:
            try:
                pa.terminate()
            except OSError:
                pass
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _load_tray_image():
    from PIL import Image, ImageDraw

    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) / "assets"
    else:
        base = ROOT / "assets"
    for name in ("hotkey_icon.ico", "app_icon.ico"):
        ico = base / name
        if ico.is_file():
            try:
                img = Image.open(ico).convert("RGBA")
                return img.resize((64, 64), Image.Resampling.LANCZOS)
            except OSError:
                continue

    # Bright fallback — visible in tray overflow (pystray/PIL ICO load often fails in frozen exe).
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, 62, 62), fill=(34, 160, 100, 255), outline=(255, 255, 255, 220), width=3)
    draw.rectangle((28, 18, 36, 34), fill=(255, 255, 255, 255))
    draw.ellipse((22, 34, 42, 50), fill=(255, 255, 255, 255))
    return img


def _is_settings_argv() -> bool:
    return any(a.lower() in ("--settings", "-s", "/settings") for a in sys.argv[1:])


def _show_settings_on_start_pref() -> bool:
    v = os.environ.get("WHISPER_HOTKEY_NO_SETTINGS_ON_START", "").strip().lower()
    if v in ("1", "true", "yes"):
        return False
    return bool(_load_prefs().get("show_settings_on_start", True))


def _set_show_settings_on_start(enabled: bool) -> None:
    p = _load_prefs()
    p["show_settings_on_start"] = bool(enabled)
    _save_prefs(p)


def _stop_program_files_installer() -> None:
    """Desktop/source launch must replace the old Program Files exe, not sit behind its mutex."""
    if getattr(sys, "frozen", False):
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        ["taskkill", "/F", "/IM", "WhisperHotkey.exe"],
        capture_output=True,
        creationflags=flags,
    )
    time.sleep(0.4)


def _acquire_single_instance() -> bool:
    """Не даём двум WhisperHotkey одновременно ловить Ctrl+Win и вставлять текст дважды."""
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183
    kernel32.CreateMutexW(None, True, "Global\\WhisperHotkeySingleInstance_v1")
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def run_settings_only() -> int:
    """Start Menu shortcut: settings without tray icon / without blocking main instance."""
    from whisper_file_log import configure, log_dir

    log = configure("whisper.hotkey", "whisper_hotkey.log")
    log.info("Whisper Hotkey --settings (standalone)")

    try:
        from whisper_version import get_version as _ver
    except ImportError:
        def _ver() -> str:
            return "dev"

    hp = _load_prefs()

    def paste(m: str) -> None:
        p = _load_prefs()
        p["paste_mode"] = m
        _save_prefs(p)
        _notify("Text output", "Restart Whisper Hotkey to apply paste mode.", False, force=True)

    def logs() -> None:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(d))  # type: ignore[attr-defined]
        except OSError:
            subprocess.run(["explorer", str(d)], check=False)

    def tray_menu_hint() -> None:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                "Groq, models, vocabulary: run Whisper Hotkey from Start menu.\n"
                "If the tray icon is missing (common when running as Admin), "
                "use this Settings shortcut anytime.",
                "Whisper Hotkey",
                0x40,
            )
        except Exception:
            pass

    from whisper_hotkey_settings_win import launch_settings_window

    launch_settings_window(
        version=_ver(),
        paste_mode=str(hp.get("paste_mode", "auto")),
        show_on_start=_show_settings_on_start_pref(),
        on_paste_mode=paste,
        on_history_file=lambda: open_history_file_standalone(),
        on_logs=logs,
        on_updates=lambda: _notify("Updates", "Run Whisper Hotkey and use Check for updates.", False, force=True),
        on_quit=lambda: None,
        on_show_tray_menu=tray_menu_hint,
        on_toggle_show_on_start=_set_show_settings_on_start,
        standalone=True,
        blocking=True,
    )
    return 0


def open_history_file_standalone() -> None:
    try:
        from whisper_hotkey_history import HISTORY_PATH

        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not HISTORY_PATH.is_file():
            HISTORY_PATH.write_text("[]", encoding="utf-8")
        os.startfile(str(HISTORY_PATH))  # type: ignore[attr-defined]
    except Exception as e:
        _notify("History", str(e)[:200], True)


def main() -> int:
    if _is_settings_argv():
        return run_settings_only()
    _stop_program_files_installer()
    if not _acquire_single_instance():
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                "Whisper Hotkey is already running (system tray).\n"
                "A second instance causes double paste — close the extra one in Task Manager.",
                "Whisper Hotkey",
                0x30,
            )
        except Exception:
            pass
        return 0

    from whisper_file_log import configure, log_dir

    log = configure("whisper.hotkey", "whisper_hotkey.log")
    log.info("Старт Whisper Hotkey (трей), ROOT=%s", ROOT)

    import pystray
    from pystray import MenuItem as Item
    from whisper_models import MODEL_PRESETS, resolve_model

    try:
        from whisper_version import get_version as _ver
    except ImportError:
        def _ver() -> str:
            return "dev"

    prefs = _load_prefs()
    model_key = str(prefs.get("model_key", "large-v3")).strip() or "large-v3"
    preset_keys = [k for k, _, _ in MODEL_PRESETS]
    if model_key not in preset_keys:
        model_key = "large-v3"

    os.environ["WHISPER_MODEL"] = model_key

    silent_start = os.environ.get("WHISPER_HOTKEY_SILENT_START", "").strip().lower() in ("1", "true", "yes")
    if not silent_start:
        if not _is_admin():
            log.warning("Запуск без прав администратора — Ctrl+Win может не работать")
            _notify(
                "Whisper Hotkey",
                f"v{_ver()} · Ctrl+Win — record. No admin rights: hotkey may fail — run as administrator.",
                True,
                force=True,
            )
        else:
            _notify(
                "Whisper Hotkey",
                f"Running as Admin (v{_ver()}). Tray icon may be hidden — settings window will open.",
                False,
                force=True,
            )

    def toast_cb(title: str, body: str, error: bool) -> None:
        _notify(title, body, error=error)

    def run_hotkey() -> None:
        from whisper_hotkey_core import WhisperHotkey

        time.sleep(0.4)
        try:
            hp = _load_prefs()
            from whisper_quality import resolve_quality_compute_type

            _dev = os.environ.get("WHISPER_DEVICE", "cuda").strip() or "cuda"
            _ct = resolve_quality_compute_type(
                device=_dev,
                explicit=os.environ.get("WHISPER_COMPUTE_TYPE")
                or str(hp.get("compute_type") or "").strip()
                or None,
            )
            svc = WhisperHotkey(
                model=resolve_model(os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"),
                device=_dev,
                compute_type=_ct,
                language=os.environ.get("WHISPER_LANGUAGE", "").strip() or None,
                status_callback=lambda m: log.info("status: %s", m),
                toast_callback=toast_cb,
                speaker_verify=bool(hp.get("speaker_verify", False)),
                speaker_threshold=_speaker_threshold_from_prefs(hp),
                paste_mode=str(hp.get("paste_mode", "auto")).strip() or "auto",
            )
            try:
                to = hp.get("transcribe_timeout_sec")
                if to is not None:
                    svc._transcribe_timeout_sec = max(30.0, float(to))
            except (TypeError, ValueError):
                pass
            try:
                mh = hp.get("max_hold_seconds")
                if mh is not None:
                    svc.max_hold_seconds = max(10.0, float(mh))
            except (TypeError, ValueError):
                pass
            svc.run()
        except Exception:
            log.exception("Фатальная ошибка hotkey")
            _notify("Whisper Hotkey", "Critical error — see whisper_hotkey.log", True, force=True)

    def set_model(icon: pystray.Icon, key: str) -> None:
        p = _load_prefs()
        p["model_key"] = key
        _save_prefs(p)
        os.environ["WHISPER_MODEL"] = key
        log.info("В prefs выбрана модель %s (нужен перезапуск)", key)
        _notify("Model", "Restart Whisper Hotkey to apply the model.", False, force=True)
        icon.update_menu()

    def set_transcribe_backend(icon: pystray.Icon, mode: str) -> None:
        p = _load_prefs()
        p["transcribe_backend"] = mode
        _save_prefs(p)
        log.info("prefs transcribe_backend=%s (применяется сразу)", mode)
        labels = {
            "auto_vram": "Авто: GPU или Groq",
            "server": "Только локальный GPU",
            "groq": "Только Groq",
            "server_then_groq": "GPU → Groq",
            "groq_then_server": "Groq → GPU",
        }
        _notify(
            "Транскрипция",
            f"Режим: {labels.get(mode, mode)}. Уже активно — перезапуск не нужен.",
            False,
            force=True,
        )
        icon.update_menu()

    def toggle_notifications(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        p["notifications"] = not bool(p.get("notifications", True))
        _save_prefs(p)
        log.info("Уведомления: %s", p["notifications"])
        if p["notifications"]:
            _notify("Notifications", "Enabled.", False, force=True)
        icon.update_menu()

    def toggle_speaker_verify(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        p["speaker_verify"] = not bool(p.get("speaker_verify", False))
        _save_prefs(p)
        log.info("Проверка голоса (prefs): %s", p["speaker_verify"])
        _notify("Voice", "Restart Whisper Hotkey to apply voice verification.", False, force=True)
        icon.update_menu()

    def start_enroll_speaker(icon: pystray.Icon, item: object) -> None:
        def w() -> None:
            _run_enroll_speaker_worker(log, _notify)
            try:
                icon.update_menu()
            except Exception:
                pass

        threading.Thread(target=w, name="whisper-enroll", daemon=True).start()

    def open_log_folder(icon: pystray.Icon, item: object) -> None:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(d))  # type: ignore[attr-defined]
        except OSError:
            subprocess.run(["explorer", str(d)], check=False)

    def open_hf_cache(icon: pystray.Icon, item: object) -> None:
        p = Path.home() / ".cache" / "huggingface"
        if p.is_dir():
            try:
                os.startfile(str(p))  # type: ignore[attr-defined]
            except OSError:
                pass
        else:
            webbrowser.open("https://huggingface.co/docs/huggingface_hub/guides/manage-cache")

    def on_quit(icon: pystray.Icon, item: object) -> None:
        log.info("Выход по команде трея")
        icon.stop()
        os._exit(0)

    def open_settings_ui(icon: pystray.Icon, item: object = None) -> None:
        """Left-click tray icon (default action) — Mac-like settings window."""
        from whisper_hotkey_settings_win import launch_settings_window

        hp = _load_prefs()
        launch_settings_window(
            version=_ver(),
            paste_mode=str(hp.get("paste_mode", "auto")),
            show_on_start=_show_settings_on_start_pref(),
            on_paste_mode=lambda m: set_paste_mode(icon, m),
            on_history_file=lambda: open_history_file(icon, None),
            on_logs=lambda: open_log_folder(icon, None),
            on_updates=lambda: hotkey_check_for_updates(icon, None),
            on_quit=lambda: on_quit(icon, None),
            on_show_tray_menu=lambda: threading.Thread(target=icon._menu, daemon=True).start(),
            on_toggle_show_on_start=_set_show_settings_on_start,
            on_prefs_saved=lambda: icon.update_menu(),
        )

    def show_tray_menu(icon: pystray.Icon, item: object = None) -> None:
        threading.Thread(target=icon._menu, daemon=True).start()

    def model_submenu():
        items = []
        for key, _mid, label in MODEL_PRESETS:
            short = label if len(label) <= 44 else label[:41] + "…"

            def make_pick(k: str):
                def pick(icon: pystray.Icon, item: object) -> None:
                    set_model(icon, k)

                return pick

            items.append(Item(f"{key}: {short}", make_pick(key)))
        return pystray.Menu(*items)

    def groq_key_status_label(item: object) -> str:
        from whisper_groq import (
            groq_api_key_from_env,
            read_hotkey_groq_api_key_pref,
            read_hotkey_groq_proxy_enabled_pref,
            read_hotkey_groq_proxy_url_pref,
            resolve_groq_proxy_url,
        )

        proxy_enabled = read_hotkey_groq_proxy_enabled_pref()
        if proxy_enabled is False:
            return "Groq: прокси выключен"
        if resolve_groq_proxy_url(read_hotkey_groq_proxy_url_pref()):
            return "Groq: прокси ✓"
        if groq_api_key_from_env():
            return "Groq ключ: из среды / .env"
        if read_hotkey_groq_api_key_pref():
            return "Groq ключ: в настройках (prefs) ✓"
        return "Groq ключ: не задан"

    def edit_groq_key(icon: pystray.Icon, item: object) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except Exception as e:
            log.warning("tkinter недоступен: %s", e)
            _notify(
                "Groq",
                "Добавь groq_api_key в whisper_hotkey_prefs.json рядом с exe или GROQ_API_KEY в .env.",
                True,
                force=True,
            )
            return
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ans = simpledialog.askstring(
                "Whisper — Groq API",
                "Ключ gsk_…\nПусто + OK — удалить из prefs.\nGROQ_API_KEY в среде важнее prefs.",
                show="*",
                parent=root,
            )
        finally:
            root.destroy()
        if ans is None:
            return
        p = _load_prefs()
        if not ans.strip():
            p.pop("groq_api_key", None)
        else:
            p["groq_api_key"] = ans.strip()
        _save_prefs(p)
        log.info("groq_api_key обновлён в prefs")
        _notify("Groq", "Сохранено в whisper_hotkey_prefs.json.", False, force=True)
        icon.update_menu()

    def clear_groq_key(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        p.pop("groq_api_key", None)
        _save_prefs(p)
        log.info("groq_api_key удалён из prefs")
        _notify("Groq", "Ключ удалён из настроек (env не трогаем).", False, force=True)
        icon.update_menu()

    def edit_groq_proxy_url(icon: pystray.Icon, item: object) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except Exception as e:
            log.warning("tkinter: %s", e)
            _notify("Прокси", "Добавь groq_proxy_url в whisper_hotkey_prefs.json или WHISPER_GROQ_PROXY_URL в .env.", True)
            return
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ans = simpledialog.askstring(
                "Groq прокси",
                "Базовый URL прокси без / в конце.\nПусто + OK — убрать из prefs.",
                parent=root,
            )
        finally:
            root.destroy()
        if ans is None:
            return
        p = _load_prefs()
        s = (ans or "").strip().rstrip("/")
        if not s:
            p.pop("groq_proxy_url", None)
        else:
            p["groq_proxy_url"] = s
        _save_prefs(p)
        _notify("Groq прокси", "URL сохранён. Ключ на стороне прокси — см. groq_proxy/README.md.", False, force=True)
        icon.update_menu()

    def toggle_groq_proxy(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        cur = p.get("groq_proxy_enabled")
        if isinstance(cur, bool):
            enabled = cur
        elif isinstance(cur, (int, float)):
            enabled = bool(cur)
        elif isinstance(cur, str):
            enabled = cur.strip().lower() in ("1", "true", "yes", "on")
        else:
            enabled = True
        p["groq_proxy_enabled"] = not enabled
        _save_prefs(p)
        _notify(
            "Groq прокси",
            "Прокси включен." if (not enabled) else "Прокси выключен (прямой Groq).",
            False,
            force=True,
        )
        icon.update_menu()

    def use_default_proxy(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        from whisper_groq import DEFAULT_GROQ_PROXY_URL

        p["groq_proxy_enabled"] = True
        p["groq_proxy_url"] = DEFAULT_GROQ_PROXY_URL
        p.pop("groq_proxy_secret", None)
        _save_prefs(p)
        _notify(
            "Groq прокси",
            "Базовый прокси выбран. При необходимости добавь секрет прокси.",
            False,
            force=True,
        )
        icon.update_menu()

    def show_proxy_help(icon: pystray.Icon, item: object) -> None:
        _notify(
            "Groq прокси — настройки",
            (
                "Для своего прокси укажи: 1) URL, 2) секрет (если сервер требует), "
                "3) включи «Использовать Groq прокси». "
                "Можно выбрать «Использовать базовый прокси» и работать сразу."
            ),
            False,
            force=True,
        )

    def edit_groq_proxy_secret(icon: pystray.Icon, item: object) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except Exception:
            _notify("Прокси", "groq_proxy_secret в prefs или WHISPER_GROQ_PROXY_SECRET в .env.", True)
            return
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ans = simpledialog.askstring(
                "Секрет прокси",
                "Как PROXY_SHARED_SECRET на Railway. Пусто + OK — убрать.",
                show="*",
                parent=root,
            )
        finally:
            root.destroy()
        if ans is None:
            return
        p = _load_prefs()
        if not (ans or "").strip():
            p.pop("groq_proxy_secret", None)
        else:
            p["groq_proxy_secret"] = ans.strip()
        _save_prefs(p)
        _notify("Groq прокси", "Секрет сохранён.", False, force=True)
        icon.update_menu()

    def clear_groq_proxy(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        p.pop("groq_proxy_enabled", None)
        p.pop("groq_proxy_url", None)
        p.pop("groq_proxy_secret", None)
        _save_prefs(p)
        _notify("Groq прокси", "URL и секрет сброшены в prefs.", False, force=True)
        icon.update_menu()

    def groq_proxy_toggle_label(item: object) -> str:
        p = _load_prefs()
        cur = p.get("groq_proxy_enabled")
        if isinstance(cur, bool):
            on = cur
        elif isinstance(cur, (int, float)):
            on = bool(cur)
        elif isinstance(cur, str):
            on = cur.strip().lower() in ("1", "true", "yes", "on")
        else:
            on = True
        mark = "✓ " if on else ""
        return f"{mark}Использовать Groq прокси"

    def open_vocab_file(icon: pystray.Icon, item: object) -> None:
        try:
            from whisper_vocab import ensure_vocab_file

            path = ensure_vocab_file()
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as e:
            _notify("Словарь", f"Не удалось открыть файл: {e}", True)

    def vocab_add_from_clipboard(icon: pystray.Icon, item: object) -> None:
        try:
            import pyperclip

            raw = pyperclip.paste() or ""
        except Exception as e:
            _notify("Словарь", f"Не удалось прочитать буфер: {e}", True)
            return
        term = (raw or "").strip().split("\n", 1)[0].strip()
        if not term:
            _notify("Словарь", "Буфер пуст.", True)
            return
        try:
            from whisper_vocab import add_term

            add_term(term)
            _notify("Словарь", f"Термин добавлен: {term}", False, force=True)
        except Exception as e:
            _notify("Словарь", f"Не удалось сохранить: {e}", True)

    def vocab_add_replacement(icon: pystray.Icon, item: object) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except Exception:
            _notify("Словарь", "Открой ~/.whisper/vocab.json вручную.", True)
            return
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            frm = simpledialog.askstring(
                "Словарь — замена",
                "Что заменять (regex, напр. 'кубернетес|кубер нетес'):",
                parent=root,
            )
            if not frm:
                return
            to = simpledialog.askstring(
                "Словарь — замена",
                f"На что заменять («{frm.strip()}»):",
                parent=root,
            )
            if not to:
                return
        finally:
            root.destroy()
        try:
            from whisper_vocab import add_replacement

            add_replacement(frm.strip(), to.strip())
            _notify("Словарь", f"Замена сохранена: {frm.strip()} → {to.strip()}", False, force=True)
        except Exception as e:
            _notify("Словарь", f"Не удалось сохранить: {e}", True)

    def vocab_show_prompt(icon: pystray.Icon, item: object) -> None:
        try:
            from whisper_vocab import build_initial_prompt

            t = build_initial_prompt(None)
            body = (t or "(пусто)")[:500]
            _notify("Словарь — подсказка", body, False, force=True)
        except Exception as e:
            _notify("Словарь", str(e)[:220], True)

    def hotkey_check_for_updates(icon: pystray.Icon, item: object) -> None:
        def worker() -> None:
            import tempfile
            import urllib.request
            import webbrowser
            from pathlib import Path

            try:
                from whisper_update_check import (
                    fetch_latest_release,
                    is_remote_newer,
                    pick_asset_url,
                    releases_repo,
                )
                from whisper_version import get_version
            except ImportError as e:
                _notify("Обновления", f"Нет модулей: {e}", True, force=True)
                return
            if os.environ.get("WHISPER_SKIP_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes"):
                _notify("Обновления", "Проверка отключена (WHISPER_SKIP_UPDATE_CHECK).", False, force=True)
                return
            try:
                cur = get_version()
            except Exception:
                cur = "?"
            rel = fetch_latest_release(force=True)
            html = f"https://github.com/{releases_repo()}/releases/latest"
            if rel is None:
                try:
                    webbrowser.open(html)
                except Exception:
                    pass
                _notify(
                    "Обновления",
                    "Не удалось получить релиз — открыта страница GitHub.",
                    False,
                    force=True,
                )
                return
            tag = (rel.get("tag_name") or "").strip()
            if not is_remote_newer(tag, cur):
                _notify("Whisper Hotkey", f"Установлена актуальная версия ({cur}).", False, force=True)
                return
            page = (rel.get("html_url") or "").strip() or html
            picked = pick_asset_url(rel, suffix=".exe", contains="whisperhotkey")
            if not picked:
                try:
                    webbrowser.open(page)
                except Exception:
                    pass
                _notify(
                    "Обновления",
                    f"Доступна {tag}. Скачай WhisperHotkeySetup (страница открыта).",
                    False,
                    force=True,
                )
                return
            name, url = picked
            try:
                fd, tmp = tempfile.mkstemp(suffix=".exe")
                os.close(fd)
                req = urllib.request.Request(url, headers={"User-Agent": "WhisperHotkey/1.0"})
                with urllib.request.urlopen(req, timeout=600) as resp:
                    Path(tmp).write_bytes(resp.read())
                os.startfile(tmp)  # type: ignore[attr-defined]
                _notify("Обновления", f"Запущен установщик: {name}", False, force=True)
            except Exception as e:
                try:
                    webbrowser.open(page)
                except Exception:
                    pass
                _notify(
                    "Обновления",
                    f"Скачивание не удалось ({e!s:.120}) — открыта страница релиза.",
                    True,
                    force=True,
                )

        threading.Thread(target=worker, name="whisper-hotkey-update", daemon=True).start()

    def _set_speaker_threshold(icon: pystray.Icon, val: float | None) -> None:
        p = _load_prefs()
        if val is None:
            p.pop("speaker_threshold", None)
        else:
            p["speaker_threshold"] = float(val)
        _save_prefs(p)
        _notify("Порог эталона", "Перезапусти Whisper Hotkey, чтобы применить.", False, force=True)
        icon.update_menu()

    def clear_speaker_threshold(icon: pystray.Icon, item: object) -> None:
        _set_speaker_threshold(icon, None)

    def set_spk_065(icon: pystray.Icon, item: object) -> None:
        _set_speaker_threshold(icon, 0.65)

    def set_spk_070(icon: pystray.Icon, item: object) -> None:
        _set_speaker_threshold(icon, 0.70)

    def edit_speaker_threshold(icon: pystray.Icon, item: object) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except Exception:
            _notify("Порог", "Нет tkinter.", True)
            return
        hp = _load_prefs()
        cur = hp.get("speaker_threshold", "")
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ans = simpledialog.askstring(
                "Порог эталона",
                "Число 0.45 … 0.99 (косинусное сходство). Пусто — убрать из prefs.",
                initialvalue=str(cur) if cur != "" else "",
                parent=root,
            )
        finally:
            root.destroy()
        if ans is None:
            return
        s = ans.strip()
        if not s:
            clear_speaker_threshold(icon, None)
            return
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            _notify("Порог", "Нужно число.", True)
            return
        if not 0.45 <= v <= 0.99:
            _notify("Порог", "Ожидается 0.45 … 0.99.", True)
            return
        _set_speaker_threshold(icon, v)

    def speaker_threshold_submenu():
        return pystray.Menu(
            Item("Сбросить prefs (env)", clear_speaker_threshold),
            Item("Порог 0.65", set_spk_065),
            Item("Порог 0.70", set_spk_070),
            Item("Своё число…", edit_speaker_threshold),
        )

    def edit_transcribe_timeout(icon: pystray.Icon, item: object) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except Exception:
            return
        hp = _load_prefs()
        cur = hp.get("transcribe_timeout_sec", "")
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ans = simpledialog.askstring(
                "Таймаут транскрипции",
                "Секунды ожидания GPU/Groq (не длина записи). Пусто — по умолчанию из env.",
                initialvalue=str(cur) if cur != "" else "",
                parent=root,
            )
        finally:
            root.destroy()
        if ans is None:
            return
        st = ans.strip()
        p = _load_prefs()
        if not st:
            p.pop("transcribe_timeout_sec", None)
        else:
            try:
                p["transcribe_timeout_sec"] = float(st.replace(",", "."))
            except ValueError:
                _notify("Таймаут", "Нужно число.", True)
                return
        _save_prefs(p)
        _notify("Таймаут", "Перезапусти Whisper Hotkey.", False, force=True)
        icon.update_menu()

    def edit_max_hold(icon: pystray.Icon, item: object) -> None:
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except Exception:
            return
        hp = _load_prefs()
        cur = hp.get("max_hold_seconds", "")
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            ans = simpledialog.askstring(
                "Макс. удержание записи",
                "Секунды (защита от переполнения памяти). Пусто — по умолчанию (120).",
                initialvalue=str(cur) if cur != "" else "",
                parent=root,
            )
        finally:
            root.destroy()
        if ans is None:
            return
        st = ans.strip()
        p = _load_prefs()
        if not st:
            p.pop("max_hold_seconds", None)
        else:
            try:
                p["max_hold_seconds"] = float(st.replace(",", "."))
            except ValueError:
                _notify("Запись", "Нужно число.", True)
                return
        _save_prefs(p)
        _notify("Запись", "Перезапусти Whisper Hotkey.", False, force=True)
        icon.update_menu()

    def set_paste_mode(icon: pystray.Icon, mode: str) -> None:
        p = _load_prefs()
        p["paste_mode"] = mode
        _save_prefs(p)
        log.info("paste_mode=%s (restart hotkey to apply)", mode)
        _notify("Text output", "Restart Whisper Hotkey to apply paste mode.", False, force=True)
        icon.update_menu()

    def paste_mode_submenu():
        cur = str(_load_prefs().get("paste_mode", "auto")).strip() or "auto"
        specs = [
            ("auto", "Paste + clipboard"),
            ("clipboard", "Clipboard only"),
            ("history_only", "History only"),
        ]
        items = []
        for mode, label in specs:
            mark = "✓ " if cur == mode else ""

            def make_pick(m: str):
                def pick(icon: pystray.Icon, item: object) -> None:
                    set_paste_mode(icon, m)

                return pick

            items.append(Item(f"{mark}{label}", make_pick(mode)))
        return pystray.Menu(*items)

    def open_history_file(icon: pystray.Icon, item: object) -> None:
        try:
            from whisper_hotkey_history import HISTORY_PATH

            HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            if not HISTORY_PATH.is_file():
                HISTORY_PATH.write_text("[]", encoding="utf-8")
            os.startfile(str(HISTORY_PATH))  # type: ignore[attr-defined]
        except Exception as e:
            _notify("History", str(e)[:200], True)

    def history_submenu():
        from whisper_hotkey_history import load_history, preview_title

        items = []
        for entry in load_history(limit=12):
            t = str(entry.get("text") or "")
            title = preview_title(t)
            if entry.get("failure"):
                title = "✗ " + title

            def make_copy(text: str):
                def pick(icon: pystray.Icon, item: object) -> None:
                    try:
                        import pyperclip

                        pyperclip.copy(text)
                        _notify("History", "Copied to clipboard.", False, force=True)
                    except Exception as ex:
                        _notify("History", str(ex)[:200], True)

                return pick

            items.append(Item(title, make_copy(t)))
        if not items:
            items.append(Item("(empty)", None, enabled=False))
        items.append(Item("Open history file…", open_history_file))
        return pystray.Menu(*items)

    def vocab_submenu():
        return pystray.Menu(
            Item("Открыть словарь…", open_vocab_file),
            Item("Добавить из буфера…", vocab_add_from_clipboard),
            Item("Добавить замену…", vocab_add_replacement),
            Item("Показать подсказку словаря", vocab_show_prompt),
        )

    def ai_mode_submenu():
        from whisper_ai_modes import ALLOWED_AI_MODE_PREFS, mode_label, normalize_ai_mode, read_hotkey_ai_mode_pref
        from whisper_groq import load_hotkey_prefs, save_hotkey_prefs

        cur = read_hotkey_ai_mode_pref()

        def set_mode(icon: pystray.Icon, mode: str) -> None:
            p = load_hotkey_prefs()
            p["ai_mode"] = normalize_ai_mode(mode)
            save_hotkey_prefs(p)
            _notify("AI Mode", mode_label(mode), False, force=True)
            icon.update_menu()

        items = []
        for mode in (
            "auto",
            "raw",
            "polish",
            "email",
            "chat",
            "code",
            "translate_en",
            "translate_ru",
        ):
            if mode not in ALLOWED_AI_MODE_PREFS:
                continue
            mark = "✓ " if cur == mode else "   "

            def make_set(m: str):
                def _act(icon: pystray.Icon, item: object = None) -> None:
                    set_mode(icon, m)

                return _act

            items.append(Item(mark + mode_label(mode), make_set(mode)))
        return pystray.Menu(*items)

    def cloud_submenu():
        def cloud_status(icon: pystray.Icon, item: object = None) -> None:
            try:
                from whisper_groq import (
                    DEFAULT_GROQ_PROXY_URL,
                    ensure_cloud_token_for_proxy,
                    fetch_cloud_me,
                    resolve_groq_proxy_url,
                    read_hotkey_groq_proxy_url_pref,
                )

                base = resolve_groq_proxy_url(read_hotkey_groq_proxy_url_pref()) or DEFAULT_GROQ_PROXY_URL
                tok = ensure_cloud_token_for_proxy(base)
                me = fetch_cloud_me(base, tok)
                _notify(
                    "Whisper Cloud",
                    f"{me.get('plan')}: {me.get('remaining_minutes')} мин осталось ({me.get('period')})",
                    False,
                    force=True,
                )
            except Exception as e:
                _notify("Whisper Cloud", str(e)[:180], True, force=True)

        def cloud_checkout(icon: pystray.Icon, item: object = None) -> None:
            try:
                from whisper_groq import (
                    DEFAULT_GROQ_PROXY_URL,
                    create_cloud_checkout,
                    ensure_cloud_token_for_proxy,
                    resolve_groq_proxy_url,
                    read_hotkey_groq_proxy_url_pref,
                )

                base = resolve_groq_proxy_url(read_hotkey_groq_proxy_url_pref()) or DEFAULT_GROQ_PROXY_URL
                tok = ensure_cloud_token_for_proxy(base)
                out = create_cloud_checkout(base, tok)
                url = out.get("checkout_url")
                if not url:
                    _notify(
                        "Whisper Cloud",
                        "Stripe не настроен — нужен grant_pro.py или STRIPE_* на Railway",
                        True,
                        force=True,
                    )
                    return
                webbrowser.open(str(url))
            except Exception as e:
                _notify("Whisper Cloud", str(e)[:180], True, force=True)

        def cloud_paste_token(icon: pystray.Icon, item: object = None) -> None:
            try:
                import tkinter as tk
                from tkinter import simpledialog

                from whisper_groq import load_hotkey_prefs, save_hotkey_prefs

                root = tk.Tk()
                root.withdraw()
                ans = simpledialog.askstring("Cloud токен", "wsk_… (пусто — очистить)", show="*")
                root.destroy()
                if ans is None:
                    return
                p = load_hotkey_prefs()
                s = ans.strip()
                if not s:
                    p.pop("cloud_token", None)
                else:
                    p["cloud_token"] = s
                save_hotkey_prefs(p)
                _notify("Whisper Cloud", "Токен сохранён" if s else "Токен очищен", False, force=True)
                icon.update_menu()
            except Exception as e:
                _notify("Whisper Cloud", str(e)[:180], True, force=True)

        return pystray.Menu(
            Item("Статус минут…", cloud_status),
            Item("Вставить токен…", cloud_paste_token),
            Item("Оформить Pro…", cloud_checkout),
        )

    def groq_api_submenu():
        return pystray.Menu(
            Item(groq_key_status_label, None, enabled=False),
            Item("Groq API ключ…", edit_groq_key),
            Item("Сбросить ключ Groq (prefs)", clear_groq_key),
            Item("Что нужно для своего прокси…", show_proxy_help),
            Item(groq_proxy_toggle_label, toggle_groq_proxy),
            Item("Использовать базовый прокси", use_default_proxy),
            Item("Свой Groq прокси URL…", edit_groq_proxy_url),
            Item("Свой Groq прокси секрет…", edit_groq_proxy_secret),
            Item("Сбросить Groq прокси", clear_groq_proxy),
        )

    def transcribe_backend_submenu():
        from whisper_groq import read_hotkey_transcribe_backend_pref, resolve_transcribe_backend_mode

        cur = resolve_transcribe_backend_mode(
            read_hotkey_transcribe_backend_pref(),
            "WHISPER_TRANSCRIBE_BACKEND",
            "WHISPER_MAC_TRANSCRIBE_BACKEND",
        )
        specs = [
            ("auto_vram", "Авто: GPU если хватает VRAM, иначе Groq"),
            ("server", "Только локальный GPU"),
            ("groq", "Только Groq (large v3)"),
            ("server_then_groq", "GPU → Groq"),
            ("groq_then_server", "Groq → GPU"),
        ]
        cur_label = dict(specs).get(cur, cur or "по умолчанию")
        items = [Item(f"Сейчас: {cur_label}", None, enabled=False)]
        for mode, label in specs:
            mark = "✓ " if cur == mode else "   "

            def make_pick(m: str):
                def pick(icon: pystray.Icon, item: object) -> None:
                    set_transcribe_backend(icon, m)

                return pick

            items.append(Item(f"{mark}{label}", make_pick(mode)))
        return pystray.Menu(*items)

    def notif_label(item: object) -> str:
        env_off = os.environ.get("WHISPER_HOTKEY_NO_NOTIFICATIONS", "").strip().lower() in ("1", "true", "yes")
        if env_off:
            return "Notifications: off (env)"
        on = bool(_load_prefs().get("notifications", True))
        return f"Notifications: {'on' if on else 'off'}"

    def spk_label(item: object) -> str:
        on = bool(_load_prefs().get("speaker_verify", False))
        return f"Voice verify: {'on' if on else 'off'} (restart)"

    def paste_label(item: object) -> str:
        pm = str(_load_prefs().get("paste_mode", "auto"))
        labels = {"auto": "paste+clipboard", "clipboard": "clipboard", "history_only": "history"}
        return f"Text output: {labels.get(pm, pm)} (restart)"

    menu = pystray.Menu(
        Item("Открыть настройки…", open_settings_ui, default=True),
        Item(f"Whisper Hotkey v{_ver()}", None, enabled=False),
        Item("Меню трея (словарь…)…", show_tray_menu),
        Item(notif_label, toggle_notifications),
        Item(spk_label, toggle_speaker_verify),
        Item("Записать эталон голоса (~45 с)…", start_enroll_speaker),
        Item(paste_label, paste_mode_submenu()),
        Item("Модель → (перезапуск)", model_submenu()),
        Item("Транскрипция →", transcribe_backend_submenu()),
        Item("Порог голоса →", speaker_threshold_submenu()),
        Item("Таймаут распознавания (сек)…", edit_transcribe_timeout),
        Item("Макс. длина записи (сек)…", edit_max_hold),
        Item("Словарь →", vocab_submenu()),
        Item("История →", history_submenu()),
        Item("AI Mode →", ai_mode_submenu()),
        Item("Whisper Cloud →", cloud_submenu()),
        Item("Groq API →", groq_api_submenu()),
        Item("Проверить обновления…", hotkey_check_for_updates),
        Item("Папка логов", open_log_folder),
        Item("Кэш моделей Hugging Face", open_hf_cache),
        Item("Выход", on_quit),
    )

    image = _load_tray_image()
    icon = pystray.Icon(
        "whisper_hotkey",
        image,
        "Whisper Hotkey — click icon for settings · Ctrl+Win record",
        menu,
    )

    def on_ready(ic: pystray.Icon) -> None:
        try:
            ic.visible = True
            log.info("Tray icon visible=True")
        except Exception:
            log.exception("Tray icon visible failed")
        threading.Thread(target=run_hotkey, name="whisper-hotkey", daemon=True).start()
        if not silent_start and _show_settings_on_start_pref():
            threading.Timer(1.2, lambda: open_settings_ui(ic)).start()

    try:
        icon.run(setup=on_ready)
    except Exception:
        log.exception("pystray icon.run failed — starting hotkey without tray")
        threading.Thread(target=run_hotkey, name="whisper-hotkey", daemon=True).start()
        if not silent_start:
            threading.Timer(1.0, lambda: open_settings_ui(icon)).start()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
