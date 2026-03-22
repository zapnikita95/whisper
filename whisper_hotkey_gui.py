"""Совместимость: раньше было окно tkinter. Сейчас — трей и уведомления (whisper_hotkey_tray)."""
from whisper_hotkey_tray import main

if __name__ == "__main__":
    raise SystemExit(main())
