"""Shim: запуск из старых батников `whisper-server.py`. Весь код — в whisper_server.py."""
from whisper_server import main

if __name__ == "__main__":
    raise SystemExit(main())
