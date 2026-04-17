#!/usr/bin/env python3
"""
Whisper Hotkey в фоне: иконка в трее, уведомления (запуск / запись / результат / ошибки).
Лог: whisper_hotkey.log рядом с exe. Отключить уведомления: трей «Уведомления» или WHISPER_HOTKEY_NO_NOTIFICATIONS=1.
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

PREFS_PATH = ROOT / "whisper_hotkey_prefs.json"
OLD_PREFS = ROOT / "whisper_hotkey_gui_prefs.json"


def _load_prefs() -> dict:
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    try:
        if OLD_PREFS.is_file():
            data = json.loads(OLD_PREFS.read_text(encoding="utf-8"))
            merged = {
                "model_key": data.get("model_key", "large-v3"),
                "notifications": True,
                "speaker_verify": False,
            }
            _save_prefs(merged)
            return merged
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {"model_key": "large-v3", "notifications": True, "speaker_verify": False}


def _save_prefs(data: dict) -> None:
    try:
        PREFS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


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
        if error and title in ("Таймаут", "Распознавание", "Модель", "Сеть или диск"):
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
                title_gap = 30.0 if title in ("Таймаут", "Распознавание") else 12.0
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
    notify("Эталон голоса", f"Через 2 с запись {sec} с — говори в обычном темпе.", False, force=True)
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
            "Эталон голоса",
            "Сохранён. Проверка голоса включена в настройках — перезапусти hotkey.",
            False,
            force=True,
        )
    except ImportError:
        log.exception("enroll: нет speaker_verify / torch")
        notify(
            "Эталон голоса",
            "Нужны зависимости: pip install -r requirements-speaker.txt и пересборка exe.",
            True,
            force=True,
        )
    except OSError as e:
        log.exception("enroll: микрофон")
        notify("Эталон голоса", f"Микрофон: {e}"[:220], True, force=True)
    except Exception as e:
        log.exception("enroll failed")
        notify("Эталон голоса", str(e)[:220], True, force=True)
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
    from PIL import Image

    if getattr(sys, "frozen", False):
        ico = Path(sys._MEIPASS) / "assets" / "app_icon.ico"
    else:
        ico = ROOT / "assets" / "app_icon.ico"
    if ico.is_file():
        return Image.open(ico)
    img = Image.new("RGB", (64, 64), color=(32, 110, 75))
    return img


def main() -> int:
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
                f"v{_ver()} · Ctrl+Win — запись. Нет прав администратора: перехват может не работать — запусти exe от администратора.",
                True,
                force=True,
            )
        else:
            _notify(
                "Whisper Hotkey",
                f"Работаю в фоне (v{_ver()}). Ctrl+Win — запись.",
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
            svc = WhisperHotkey(
                model=resolve_model(os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"),
                device=os.environ.get("WHISPER_DEVICE", "cuda").strip() or "cuda",
                compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
                language=os.environ.get("WHISPER_LANGUAGE", "").strip() or None,
                status_callback=lambda m: log.info("status: %s", m),
                toast_callback=toast_cb,
                speaker_verify=bool(hp.get("speaker_verify", False)),
                speaker_threshold=_speaker_threshold_from_env(),
            )
            svc.run()
        except Exception:
            log.exception("Фатальная ошибка hotkey")
            _notify("Whisper Hotkey", "Критическая ошибка — см. whisper_hotkey.log", True, force=True)

    def set_model(icon: pystray.Icon, key: str) -> None:
        p = _load_prefs()
        p["model_key"] = key
        _save_prefs(p)
        os.environ["WHISPER_MODEL"] = key
        log.info("В prefs выбрана модель %s (нужен перезапуск)", key)
        _notify("Модель", "Перезапусти Whisper Hotkey, чтобы применить модель.", False, force=True)
        icon.update_menu()

    def set_transcribe_backend(icon: pystray.Icon, mode: str) -> None:
        p = _load_prefs()
        p["transcribe_backend"] = mode
        _save_prefs(p)
        log.info("В prefs transcribe_backend=%s (нужен перезапуск, если не переопределяет env)", mode)
        _notify(
            "Транскрипция",
            "Перезапусти Whisper Hotkey, чтобы применить цепочку (если не задан WHISPER_TRANSCRIBE_BACKEND в среде).",
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
            _notify("Уведомления", "Включены.", False, force=True)
        icon.update_menu()

    def toggle_speaker_verify(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        p["speaker_verify"] = not bool(p.get("speaker_verify", False))
        _save_prefs(p)
        log.info("Проверка голоса (prefs): %s", p["speaker_verify"])
        _notify("Голос", "Перезапусти Whisper Hotkey, чтобы применить проверку голоса.", False, force=True)
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
        p["groq_proxy_enabled"] = True
        p["groq_proxy_url"] = "https://whisper-groq-proxy-production.up.railway.app"
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

    def vocab_submenu():
        return pystray.Menu(
            Item("Открыть словарь…", open_vocab_file),
            Item("Добавить из буфера…", vocab_add_from_clipboard),
            Item("Добавить замену…", vocab_add_replacement),
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
            ("server", "Только локальный GPU"),
            ("groq", "Только Groq (large v3)"),
            ("server_then_groq", "GPU → Groq"),
            ("groq_then_server", "Groq → GPU"),
        ]
        items = []
        for mode, label in specs:
            mark = "✓ " if cur == mode else ""
            short = label if len(label) <= 48 else label[:45] + "…"

            def make_pick(m: str):
                def pick(icon: pystray.Icon, item: object) -> None:
                    set_transcribe_backend(icon, m)

                return pick

            items.append(Item(f"{mark}{short}", make_pick(mode)))
        return pystray.Menu(*items)

    def notif_label(item: object) -> str:
        env_off = os.environ.get("WHISPER_HOTKEY_NO_NOTIFICATIONS", "").strip().lower() in ("1", "true", "yes")
        if env_off:
            return "Уведомления: выкл (переменная среды)"
        on = bool(_load_prefs().get("notifications", True))
        return f"Уведомления: {'вкл' if on else 'выкл'}"

    def spk_label(item: object) -> str:
        on = bool(_load_prefs().get("speaker_verify", False))
        return f"Проверка голоса: {'вкл' if on else 'выкл'} (перезапуск)"

    menu = pystray.Menu(
        Item(f"Whisper Hotkey v{_ver()}", None, enabled=False),
        Item(notif_label, toggle_notifications),
        Item(spk_label, toggle_speaker_verify),
        Item("Записать эталон голоса (~45 с)…", start_enroll_speaker),
        Item("Модель → (перезапуск)", model_submenu()),
        Item("Транскрипция → (перезапуск)", transcribe_backend_submenu()),
        Item("Словарь →", vocab_submenu()),
        Item("Groq API →", groq_api_submenu()),
        Item("Папка с логами", open_log_folder),
        Item("Кэш моделей Hugging Face", open_hf_cache),
        Item("Выход", on_quit),
    )

    image = _load_tray_image()
    icon = pystray.Icon(
        "whisper_hotkey",
        image,
        "Whisper Hotkey — Ctrl+Win",
        menu,
    )

    def on_ready(ic: pystray.Icon) -> None:
        threading.Thread(target=run_hotkey, name="whisper-hotkey", daemon=True).start()

    icon.run(setup=on_ready)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
