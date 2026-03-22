#!/usr/bin/env python3
"""
Whisper Hotkey в фоне: иконка в трее, уведомления (запуск / запись / результат / ошибки).
Лог: whisper_hotkey.log рядом с exe. Отключить уведомления: трей «Уведомления» или WHISPER_HOTKEY_NO_NOTIFICATIONS=1.

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
            merged = {"model_key": data.get("model_key", "large-v3"), "notifications": True}
            _save_prefs(merged)
            return merged
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {"model_key": "large-v3", "notifications": True}


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


def _notify(title: str, body: str, error: bool = False) -> None:
    if not _notifications_enabled():
        return
    try:
        from plyer import notification

        notification.notify(
            title=title[:63],
            message=body[:255],
            app_name="Whisper Hotkey",
            timeout=8,
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

    if not _is_admin():
        log.warning("Запуск без прав администратора — Ctrl+Win может не работать")
        _notify(
            "Whisper Hotkey",
            "Нет прав администратора: перехват Ctrl+Win может не работать. Запусти exe от администратора.",
            True,
        )
    else:
        _notify("Whisper Hotkey", f"Работаю в фоне (v{_ver()}). Ctrl+Win — запись.", False)

    def toast_cb(title: str, body: str, error: bool) -> None:
        _notify(title, body, error=error)

    def run_hotkey() -> None:
        from whisper_hotkey_core import WhisperHotkey

        time.sleep(0.4)
        try:
            svc = WhisperHotkey(
                model=resolve_model(os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"),
                device=os.environ.get("WHISPER_DEVICE", "cuda").strip() or "cuda",
                compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
                language=os.environ.get("WHISPER_LANGUAGE", "").strip() or None,
                status_callback=lambda m: log.info("status: %s", m),
                toast_callback=toast_cb,
            )
            svc.run()
        except Exception:
            log.exception("Фатальная ошибка hotkey")
            _notify("Whisper Hotkey", "Критическая ошибка — см. whisper_hotkey.log", True)

    def set_model(icon: pystray.Icon, key: str) -> None:
        p = _load_prefs()
        p["model_key"] = key
        _save_prefs(p)
        os.environ["WHISPER_MODEL"] = key
        log.info("В prefs выбрана модель %s (нужен перезапуск)", key)
        _notify("Модель", "Перезапусти Whisper Hotkey, чтобы применить модель.", False)
        icon.update_menu()

    def toggle_notifications(icon: pystray.Icon, item: object) -> None:
        p = _load_prefs()
        p["notifications"] = not bool(p.get("notifications", True))
        _save_prefs(p)
        log.info("Уведомления: %s", p["notifications"])
        if p["notifications"]:
            _notify("Уведомления", "Включены.", False)
        icon.update_menu()

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

    def notif_label(item: object) -> str:
        env_off = os.environ.get("WHISPER_HOTKEY_NO_NOTIFICATIONS", "").strip().lower() in ("1", "true", "yes")
        if env_off:
            return "Уведомления: выкл (переменная среды)"
        on = bool(_load_prefs().get("notifications", True))
        return f"Уведомления: {'вкл' if on else 'выкл'}"

    menu = pystray.Menu(
        Item(f"Whisper Hotkey v{_ver()}", None, enabled=False),
        Item(notif_label, toggle_notifications),
        Item("Модель → (перезапуск)", model_submenu()),
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
