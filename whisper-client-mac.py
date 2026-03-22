#!/usr/bin/env python3
"""
Клиент для Mac: запись с микрофона, отправка на Windows-сервер, вставка текста.
Запуск: python3 whisper-client-mac.py --server http://192.168.1.100:8000
Горячая клавиша: при запуске в терминале спросит строку (Enter = ⌃+⇧+⌥), либо --hotkey, либо --bind-hotkey

Рядом с Portal (⌘+⌃+P/C/V): по умолчанию ⌃+⇧+⌥ — три модификатора, без печатного символа (не пишет ` в поле и не бьётся с «терминал» в Cursor).
Переопределение: WHISPER_MAC_HOTKEY или флаг --hotkey; в WhisperClient.app хоткей задаётся в packaging/mac/run.sh.
См. PORTAL_AND_WHISPER_MAC.md

Журнал (вставка/сервер): ~/Library/Logs/WhisperMacClient.log (если нет прав — /tmp/WhisperMacClient.log); в Console фильтр «WHISPER_MAC»; после каждой строки flush на диск.
Полный текст распознавания в лог: WHISPER_MAC_DEBUG=1.
Перехват клавиш — отдельный поток с автоперезапуском; иконка 🎤/🔴 в строке меню — rumps (рекомендуется: pip install rumps; pick_python выберет интерпретатор с rumps).
Уведомления из .app — Contents/MacOS/whisper_notify (не процесс Python). Хоткей по умолчанию без ⌘ (рядом с Portal).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_rp = Path(__file__).resolve().parent
if str(_rp) not in sys.path:
    sys.path.insert(0, str(_rp))

try:
    import rumps
except ImportError:
    rumps = None  # type: ignore[misc, assignment]

try:
    import requests
    import sounddevice as sd
    import numpy as np
    import soundfile as sf
    from pynput import keyboard
    from pynput.keyboard import Controller as KeyboardController
    from pynput.keyboard import Key
    from pynput.keyboard import KeyCode
    import pyperclip
except ImportError as e:
    print(f"Ошибка импорта: {e}", file=sys.stderr)
    print("Установи: pip3 install requests sounddevice numpy soundfile 'pynput>=1.8.1' pyperclip", file=sys.stderr)
    sys.exit(1)


_MAC_LOGGER = logging.getLogger("whisper_mac")
_LOG_PATH: Path | None = None


class _FlushingFileHandler(logging.FileHandler):
    """После каждой записи flush — иначе при краше .app последние строки не попадают на диск."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_whisper_mac_logging() -> Path:
    """Файл ~/Library/Logs/WhisperMacClient.log; при ошибке — /tmp; всегда flush."""
    global _LOG_PATH
    fmt = logging.Formatter("%(asctime)s [WHISPER_MAC] %(levelname)s %(message)s")
    _MAC_LOGGER.setLevel(logging.DEBUG)
    _MAC_LOGGER.handlers.clear()

    candidates: list[Path] = []
    try:
        log_dir = Path.home() / "Library" / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        candidates.append(log_dir / "WhisperMacClient.log")
    except OSError:
        pass
    candidates.append(Path(tempfile.gettempdir()) / "WhisperMacClient.log")

    log_path = Path(tempfile.gettempdir()) / "WhisperMacClient.log"
    fh: logging.Handler | None = None
    for p in candidates:
        try:
            fh = _FlushingFileHandler(p, encoding="utf-8")
            log_path = p
            break
        except OSError as e:
            print(f"[Client] Лог-файл {p}: {e}", file=sys.stderr, flush=True)

    if fh is None:
        fh = logging.StreamHandler(sys.stderr)
        print("[Client] Пишу лог только в stderr (не удалось создать файл).", file=sys.stderr, flush=True)

    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    _MAC_LOGGER.addHandler(fh)
    if sys.stdout.isatty():
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.setLevel(logging.INFO)
        _MAC_LOGGER.addHandler(sh)

    _LOG_PATH = log_path if fh is not None and isinstance(fh, _FlushingFileHandler) else None

    def _excepthook(exc_type, exc, tb) -> None:
        if _MAC_LOGGER.handlers:
            _MAC_LOGGER.error("uncaught_exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    _MAC_LOGGER.info("logging_ok path=%s", log_path)
    return log_path


def _mac_log(level: str, msg: str, *args: object) -> None:
    log_fn = getattr(_MAC_LOGGER, level.lower(), None)
    if log_fn:
        log_fn(msg, *args)
    else:
        _MAC_LOGGER.info(msg, *args)


def _fastapi_error_detail(resp: requests.Response) -> str:
    """Текст из JSON FastAPI/Starlette (`detail`) — чтобы в уведомлении было не только «500 Server Error»."""
    try:
        j = resp.json()
    except ValueError:
        body = (resp.text or "").strip()
        return (body[:400] if body else f"HTTP {resp.status_code}")
    if not isinstance(j, dict):
        return f"HTTP {resp.status_code}"
    d = j.get("detail")
    if isinstance(d, str):
        return d
    if isinstance(d, list):
        parts: list[str] = []
        for item in d[:5]:
            if isinstance(item, dict):
                parts.append(str(item.get("msg", item)))
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else f"HTTP {resp.status_code}"
    return f"HTTP {resp.status_code}"


def mac_banner_notification(title: str, body: str = "") -> None:
    """macOS: баннер в Центре уведомлений. Из .app — бинарь whisper_notify (не «Python»); иначе osascript."""
    if sys.platform != "darwin":
        return
    if os.environ.get("WHISPER_MAC_NO_NOTIFICATIONS") == "1":
        return
    t = (title or "Whisper Client").strip()[:200]
    b = (body or "").strip()[:650]
    payload = (t + "\n" + b).encode("utf-8")
    tool = (os.environ.get("WHISPER_NOTIFY_TOOL") or "").strip()
    if tool and Path(tool).is_file() and os.access(tool, os.X_OK):
        try:
            subprocess.run(
                [tool],
                input=payload,
                capture_output=True,
                timeout=8.0,
                check=False,
            )
            return
        except Exception:
            _MAC_LOGGER.debug("whisper_notify_tool_failed", exc_info=True)
    esc_t = t.replace("\\", "\\\\").replace('"', '\\"')
    esc_b = b.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{esc_b}" with title "{esc_t}"',
            ],
            check=False,
            capture_output=True,
            timeout=10.0,
        )
    except Exception:
        pass


def _mac_notify_progress(body: str) -> None:
    """«Отправка на сервер» — по умолчанию только при запуске из .app (меньше шума в терминале)."""
    if os.environ.get("WHISPER_MAC_NOTIFY_PROGRESS", "1" if os.environ.get("WHISPER_FROM_APP_BUNDLE") else "0") != "1":
        return
    mac_banner_notification("Whisper", body)


def run_mac_update_flow(*, notify_always: bool = False, notify_newer_only: bool = False) -> None:
    """Проверка GitHub Releases; при наличии .dmg — скачать в ~/Downloads."""
    import urllib.request
    import webbrowser

    try:
        from whisper_update_check import fetch_latest_release, is_remote_newer, pick_asset_url
        from whisper_version import get_version
    except ImportError:
        mac_banner_notification("Whisper", "Обнови WhisperClient.app (нет модулей версии/обновлений).")
        return

    cur = get_version()
    rel = fetch_latest_release()
    if rel is None:
        if notify_always:
            mac_banner_notification("Whisper", "Не удалось связаться с GitHub (сеть или лимит API).")
        _mac_log("warning", "update_check_no_release_response")
        return
    tag = (rel.get("tag_name") or "").strip()
    if not is_remote_newer(tag, cur):
        if notify_always:
            mac_banner_notification("Whisper", f"Установлена актуальная версия ({cur}).")
        return
    if notify_newer_only and not notify_always:
        mac_banner_notification(
            "Whisper",
            f"Доступна версия {tag}. Меню → Проверить обновления…",
        )
        return
    picked = pick_asset_url(rel, suffix=".dmg", contains="whisperclient")
    html = (rel.get("html_url") or "").strip() or "https://github.com/zapnikita95/whisper/releases"
    if not picked:
        webbrowser.open(html)
        mac_banner_notification("Whisper", "Открыта страница релиза — скачай DMG вручную.")
        return
    name, url = picked
    dest = Path.home() / "Downloads" / name
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WhisperMacClient/1.0"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            dest.write_bytes(resp.read())
        mac_banner_notification(
            "Whisper",
            f"Скачано {dest.name} — открой DMG и перетащи Whisper Client в Программы.",
        )
        _mac_log("info", "update_downloaded path=%s", dest)
    except Exception as e:
        _MAC_LOGGER.exception("update_download_failed")
        webbrowser.open(html)
        mac_banner_notification("Whisper", f"Скачивание не удалось ({e!s:.80}) — открыта страница релиза.")


def tray_icon_path() -> str | None:
    """Иконка для строки меню: WHISPER_MAC_RESOURCES (.app), рядом со скриптом, assets репозитория."""
    res = (os.environ.get("WHISPER_MAC_RESOURCES") or "").strip()
    if res:
        base = Path(res)
        for name in ("AppIcon.icns", "AppIcon.png"):
            p = base / name
            if p.is_file():
                return str(p)
    here = Path(__file__).resolve().parent
    for name in ("AppIcon.icns", "AppIcon.png"):
        p = here / name
        if p.is_file():
            return str(p)
    assets = here.parent / "assets" / "AppIcon.icns"
    if assets.is_file():
        return str(assets)
    return None


def _check_pynput_py313() -> None:
    """CPython 3.13 добавил Thread._handle — ломает pynput < 1.8 (TypeError: ThreadHandle not callable)."""
    if sys.version_info < (3, 13):
        return
    try:
        from importlib.metadata import version as pkg_version
    except ImportError:
        return
    raw = pkg_version("pynput")
    nums: list[int] = []
    for part in raw.split(".")[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    while len(nums) < 3:
        nums.append(0)
    if tuple(nums) < (1, 8, 0):
        print(
            f"[Client] У тебя Python 3.13 и pynput {raw} — глобальные клавиши падают.\n"
            f"[Client] Обнови: pip3 install -U 'pynput>=1.8.1'",
            file=sys.stderr,
        )
        sys.exit(1)


# Вызов перенесён в main() после configure_whisper_mac_logging — иначе при .app ошибка не попадает в файл лога.


# --- Модификаторы pynput → каноническое имя
_MOD_MAP: dict[Key, str] = {
    Key.cmd_l: "cmd",
    Key.cmd_r: "cmd",
    Key.cmd: "cmd",
    Key.alt_l: "alt",
    Key.alt_r: "alt",
    Key.alt: "alt",
    Key.ctrl_l: "ctrl",
    Key.ctrl_r: "ctrl",
    Key.ctrl: "ctrl",
    Key.shift_l: "shift",
    Key.shift_r: "shift",
    Key.shift: "shift",
}

_MOD_ALIASES = {
    "cmd": "cmd",
    "command": "cmd",
    "super": "cmd",
    "win": "cmd",
    "⌘": "cmd",
    "alt": "alt",
    "option": "alt",
    "⌥": "alt",
    "ctrl": "ctrl",
    "control": "ctrl",
    "^": "ctrl",
    "shift": "shift",
}

# Синонимы не-буквенных клавиш → один символ для токена c:X
_KEY_ALIASES = {
    "grave": "`",
    "backtick": "`",
    "tick": "`",
    "rbracket": "]",
    "bracket_right": "]",
    "rb": "]",
    "lbracket": "[",
    "bracket_left": "[",
    "lb": "[",
    "comma": ",",
    "period": ".",
    "dot": ".",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "quote": "'",
    "apostrophe": "'",
    "minus": "-",
    "hyphen": "-",
    "equals": "=",
    "plus": "+",
}

_NAMED_KEY_TOKENS = frozenset(
    n
    for n in dir(Key)
    if not n.startswith("_")
    and not callable(getattr(Key, n, None))
    and isinstance(getattr(Key, n, None), Key)
)


def key_event_token(key) -> str | None:
    """Один токен для текущего события клавиши (для сравнения с HotkeySpec)."""
    if key in _MOD_MAP:
        return f"m:{_MOD_MAP[key]}"
    if isinstance(key, Key):
        return f"n:{key.name}"
    if isinstance(key, KeyCode):
        if key.char:
            ch = key.char
            if ch.isprintable() and ch not in "\r":
                return f"c:{ch}"
        if key.vk is not None:
            return f"v:{int(key.vk)}"
    return None


def is_valid_hotkey_tokens(tokens: frozenset[str]) -> bool:
    """Можно ли считать набор завершённым сочетанием (для --bind-hotkey)."""
    mods = [t for t in tokens if t.startswith("m:")]
    others = [t for t in tokens if not t.startswith("m:")]
    if len(mods) < 1:
        return False
    if not others:
        return len(mods) >= 2
    return len(others) >= 1


def validate_spec_tokens(tokens: frozenset[str]) -> None:
    if len(tokens) < 2:
        raise ValueError("Нужно минимум две клавиши в сочетании (например cmd+alt или ctrl+`).")
    if not is_valid_hotkey_tokens(tokens):
        raise ValueError(
            "Нужен хотя бы один модификатор (cmd/alt/ctrl/shift) и ещё клавиша, "
            "либо два модификатора (как cmd+alt)."
        )


@dataclass(frozen=True)
class HotkeySpec:
    tokens: frozenset[str]

    @staticmethod
    def default_mac_with_portal() -> HotkeySpec:
        """⌃+⇧+⌥ — только модификаторы: не вводят символ в текст и не совпадают с ⌃⇧` в Cursor (терминал)."""
        return HotkeySpec(frozenset({"m:shift", "m:ctrl", "m:alt"}))

    @staticmethod
    def default_option_ctrl() -> HotkeySpec:
        """⌥+⌃ (старое умолчание; может мешать другим приложениям с Ctrl)."""
        return HotkeySpec(frozenset({"m:alt", "m:ctrl"}))


def parse_hotkey_string(s: str) -> HotkeySpec:
    s = s.strip()
    if not s:
        raise ValueError("Пустая строка --hotkey")
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", s) if p.strip()]
    if not parts:
        raise ValueError("Пустое сочетание")
    toks: set[str] = set()
    for p in parts:
        if p in _MOD_ALIASES:
            toks.add(f"m:{_MOD_ALIASES[p]}")
        elif p in _KEY_ALIASES:
            toks.add(f"c:{_KEY_ALIASES[p]}")
        elif re.fullmatch(r"vk:\d+", p):
            toks.add(f"v:{int(p[3:])}")
        elif len(p) == 1:
            toks.add(f"c:{p}")
        elif p in _NAMED_KEY_TOKENS:
            toks.add(f"n:{p}")
        else:
            raise ValueError(
                f"Неизвестная клавиша «{p}». Примеры: cmd, alt, ctrl, shift, grave, rbracket, f5, vk:50"
            )
    ft = frozenset(toks)
    validate_spec_tokens(ft)
    return HotkeySpec(ft)


def describe_hotkey(spec: HotkeySpec) -> str:
    """Человекочитаемо для логов."""
    mod_order = ("cmd", "ctrl", "alt", "shift")
    mod_labels = {"cmd": "⌘", "alt": "⌥", "ctrl": "⌃", "shift": "⇧"}
    mods: list[str] = []
    keys: list[str] = []
    for t in spec.tokens:
        if t.startswith("m:"):
            name = t[2:]
            mods.append((mod_order.index(name) if name in mod_order else 99, mod_labels.get(name, name)))
        elif t.startswith("c:"):
            ch = t[2:]
            if ch == "`":
                keys.append("`")
            elif ch in "'\"\\":
                keys.append(repr(ch))
            else:
                keys.append(ch)
        elif t.startswith("n:"):
            keys.append(t[2:])
        elif t.startswith("v:"):
            keys.append(f"vk:{t[2:]}")
    mods.sort(key=lambda x: x[0])
    parts = [m[1] for m in mods] + sorted(keys)
    return "+".join(parts) if parts else str(spec.tokens)


def bind_hotkey_interactive(timeout: float = 90.0) -> HotkeySpec:
    print(
        "[Client] Привязка: зажми целиком сочетание (например ⌃+` или ⌃+]), затем отпусти все клавиши.",
        flush=True,
    )
    print("[Client] Ctrl+C — отмена и выход.", flush=True)
    pressed: set[str] = set()
    last_good: frozenset[str] | None = None
    done = threading.Event()
    out: list[HotkeySpec | None] = [None]

    def on_press(key):
        t = key_event_token(key)
        if t:
            pressed.add(t)

    def on_release(key):
        nonlocal last_good
        snap = frozenset(pressed)
        if is_valid_hotkey_tokens(snap):
            last_good = snap
        t = key_event_token(key)
        if t:
            pressed.discard(t)
        if not pressed and last_good is not None:
            try:
                validate_spec_tokens(last_good)
            except ValueError as e:
                print(f"[Client] Сочетание не подходит: {e}", flush=True)
                last_good = None
                return
            out[0] = HotkeySpec(last_good)
            print(f"[Client] Запомнил токены: {sorted(last_good)}", flush=True)
            done.set()

    with keyboard.Listener(
        on_press=on_press, on_release=on_release, suppress=False
    ) as listener:
        if done.wait(timeout):
            assert out[0] is not None
            return out[0]
    print("[Client] Таймаут привязки — остаётся ⌃+⇧+⌥ (shift+ctrl+alt).", flush=True)
    return HotkeySpec.default_mac_with_portal()


class WhisperClientMac:
    def __init__(
        self,
        server_url: str,
        language: str | None = None,
        spoken_punctuation: bool = True,
        hotkey: HotkeySpec | None = None,
        *,
        speaker_verify: bool = False,
        speaker_threshold: float | None = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.language = language
        self.spoken_punctuation = spoken_punctuation
        self.hotkey = hotkey or HotkeySpec.default_mac_with_portal()
        self._hotkey_label = describe_hotkey(self.hotkey)
        self.sample_rate = 16000
        self.channels = 1
        self._lock = threading.Lock()
        self._recording = False
        self._stop_record = threading.Event()
        # Состояние глобального hotkey (pynput иногда теряет key_up — без сброса ⌃⌥ «залипает» в памяти)
        self._hk_lock = threading.Lock()
        self._hk_pressed: set[str] = set()
        self._hk_combo_active = False
        self._hk_suppress = False
        self._record_thread: threading.Thread | None = None
        self._audio_chunks: list[bytes] = []
        self._busy = False
        self._kbd = KeyboardController()
        # Перезапуск глобального Listener после распознавания (macOS часто убивает tap после Cmd+V / synthetic keys)
        self._listener_ref: keyboard.Listener | None = None
        self._listener_ref_lock = threading.Lock()
        self._listener_thread: threading.Thread | None = None
        self._listener_start_lock = threading.Lock()
        self._run_stop = False
        self._work_lock = threading.Lock()
        # PID процесса с полем ввода (frontmost при старте записи) — перед Cmd+V возвращаем фокус туда.
        self._paste_target_unix_id: int | None = None
        self._speaker_verify = speaker_verify
        self._speaker_threshold = speaker_threshold

    def request_shutdown(self) -> None:
        """Остановка клиента (меню «Выход», SIGINT)."""
        self._run_stop = True
        self._kick_listener_restart(force=True)

    def _ensure_listener_thread(self) -> None:
        """Поток pynput не должен «тихо умереть» и гасить весь клиент — поднимаем снова."""
        with self._listener_start_lock:
            if self._run_stop:
                return
            t = self._listener_thread
            if t is not None and t.is_alive():
                return
            had_dead = t is not None
            if had_dead:
                _mac_log(
                    "warning",
                    "listener_thread_restarting (previous thread dead; hotkeys were inactive)",
                )
                try:
                    mac_banner_notification(
                        "Whisper",
                        "Перехват клавиш перезапущен — снова можно диктовать.",
                    )
                except Exception:
                    pass
            self._listener_thread = threading.Thread(
                target=self._listener_loop,
                name="whisper-pynput-listener",
                daemon=False,
            )
            self._listener_thread.start()

    def _reset_hotkey_tracker(self) -> None:
        """Сброс модели «какие клавиши зажаты» — после вставки и после цикла распознавания."""
        with self._hk_lock:
            self._hk_suppress = False
            self._hk_pressed.clear()
            self._hk_combo_active = False

    def _kick_listener_restart(self, *, force: bool = False) -> None:
        """Останавливает текущий Listener; поток _listener_loop поднимет новый tap."""
        if not force and self._run_stop:
            return
        with self._listener_ref_lock:
            lr = self._listener_ref
        if lr is not None:
            try:
                lr.stop()
            except Exception:
                pass

    def _schedule_listener_kick(self, delay: float = 0.28) -> None:
        """Отложенный restart tap: сразу после Cmd+V из потока work иногда ловится дедлок/залипание CGEventTap."""

        def _run() -> None:
            time.sleep(delay)
            try:
                self._kick_listener_restart()
                _mac_log("debug", "listener_kick_after_delay delay=%.2fs", delay)
            except Exception:
                _MAC_LOGGER.exception("listener_kick_scheduled_failed")

        threading.Thread(target=_run, name="whisper-listener-kick", daemon=True).start()

    def _on_press_hotkey(self, key) -> None:
        target = self.hotkey.tokens
        try:
            t = key_event_token(key)
            should_start = False
            with self._hk_lock:
                if self._hk_suppress:
                    return
                if t:
                    self._hk_pressed.add(t)
                if frozenset(self._hk_pressed) == target and not self._hk_combo_active:
                    self._hk_combo_active = True
                    should_start = True
            if should_start:
                self._start_recording()
        except Exception:
            _MAC_LOGGER.exception("on_press_hotkey")

    def _on_release_hotkey(self, key) -> None:
        target = self.hotkey.tokens
        try:
            t = key_event_token(key)
            should_stop = False
            with self._hk_lock:
                if self._hk_suppress:
                    return
                if t:
                    self._hk_pressed.discard(t)
                if frozenset(self._hk_pressed) != target:
                    if self._hk_combo_active:
                        self._hk_combo_active = False
                        should_stop = True
            if should_stop:
                self._stop_recording_and_process()
        except Exception:
            _MAC_LOGGER.exception("on_release_hotkey")

    def _listener_loop(self) -> None:
        """Отдельный поток: бесконечно поднимает pynput Listener; при падении tap — пауза и снова."""
        err_backoff = 0.25
        while not self._run_stop:
            try:
                with keyboard.Listener(
                    on_press=self._on_press_hotkey,
                    on_release=self._on_release_hotkey,
                    suppress=False,
                ) as listener:
                    with self._listener_ref_lock:
                        self._listener_ref = listener
                    try:
                        listener.join()
                    finally:
                        with self._listener_ref_lock:
                            if self._listener_ref is listener:
                                self._listener_ref = None
            except Exception:
                _MAC_LOGGER.exception("pynput Listener crashed; will retry")
                _mac_log(
                    "warning",
                    "hotkey_listener_restart_after_error backoff=%.2fs",
                    err_backoff,
                )
                time.sleep(err_backoff)
                err_backoff = min(err_backoff * 1.6, 4.0)
                continue
            err_backoff = 0.25
            if self._run_stop:
                break
            _mac_log("debug", "listener_join_ended (kick or macOS); restart after pause")
            time.sleep(0.22)

    def _release_sticky_modifiers(self) -> None:
        """Сбрасываем модификаторы после горячих клавиш — иначе они «дотягиваются» до синтетической вставки."""
        for k in (
            Key.cmd,
            Key.cmd_l,
            Key.cmd_r,
            Key.alt,
            Key.alt_l,
            Key.alt_r,
            Key.shift,
            Key.shift_l,
            Key.shift_r,
            Key.ctrl,
            Key.ctrl_l,
            Key.ctrl_r,
        ):
            try:
                self._kbd.release(k)
            except Exception:
                pass

    def _copy_to_clipboard_mac(self, text: str) -> None:
        """Нативный pbcopy — надёжнее по таймингу, чем pyperclip сразу перед Cmd+V."""
        subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            check=True,
            timeout=5.0,
        )

    def _clipboard_preview(self, max_len: int = 120) -> str:
        try:
            r = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if r.returncode != 0:
                return ""
            s = (r.stdout or "").replace("\r\n", "\n").replace("\r", "\n")
            if len(s) > max_len:
                return s[:max_len] + "…"
            return s
        except Exception:
            return ""

    def _clipboard_matches_expected(self, expected: str) -> bool:
        try:
            r = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if r.returncode != 0:
                return False
            got = (r.stdout or "").replace("\r\n", "\n").replace("\r", "\n")
            exp = expected.replace("\r\n", "\n").replace("\r", "\n")
            return got == exp
        except Exception:
            return False

    def _snapshot_frontmost_unix_pid(self) -> int | None:
        """Кто был активным при зажатии хоткея — туда же шлём Cmd+V после распознавания."""
        try:
            r = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to return unix id of first process whose frontmost is true',
                ],
                capture_output=True,
                text=True,
                timeout=2.5,
            )
            if r.returncode != 0:
                _mac_log(
                    "warning",
                    "snapshot_frontmost_failed code=%s err=%s",
                    r.returncode,
                    (r.stderr or "").strip(),
                )
                return None
            pid = int((r.stdout or "").strip())
        except (ValueError, subprocess.TimeoutExpired, OSError) as e:
            _mac_log("warning", "snapshot_frontmost_parse_error %s", e)
            return None
        mine = os.getpid()
        if pid == mine:
            _mac_log(
                "warning",
                "frontmost_pid=%s совпадает с клиентом — кликни в поле ввода и повтори (иначе Cmd+V уйдёт не туда)",
                pid,
            )
            return None
        _mac_log("info", "paste_target_captured unix_pid=%s", pid)
        return pid

    def _activate_process_by_unix_id(self, uid: int) -> bool:
        if uid <= 0 or uid == os.getpid():
            return False
        try:
            r = subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'tell application "System Events" to set frontmost of first process whose unix id is {uid} to true',
                ],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if r.returncode != 0:
                _mac_log(
                    "warning",
                    "activate_pid=%s failed code=%s err=%s",
                    uid,
                    r.returncode,
                    (r.stderr or "").strip(),
                )
                return False
            time.sleep(0.35)
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            _mac_log("warning", "activate_pid=%s exception=%s", uid, e)
            return False

    def _paste_via_system_events(self) -> bool:
        """Cmd+V через key code 9 (клавиша V), без keystroke — стабильнее при разных раскладках."""
        r = subprocess.run(
            [
                "osascript",
                "-e",
                "delay 0.18",
                "-e",
                'tell application "System Events" to key code 9 using command down',
            ],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if r.returncode != 0:
            _mac_log(
                "warning",
                "paste_keycode_failed code=%s err=%s",
                r.returncode,
                (r.stderr or "").strip(),
            )
        return r.returncode == 0

    def _record_worker(self, max_duration: float = 120.0) -> None:
        chunks = []
        max_chunks = int(self.sample_rate / 1024 * max_duration) + 1
        n = 0
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                blocksize=1024,
            ) as stream:
                while not self._stop_record.is_set() and n < max_chunks:
                    data, overflowed = stream.read(1024)
                    if overflowed:
                        print("[Client] Переполнение буфера!", flush=True)
                    chunks.append(data.tobytes())
                    n += 1
            with self._lock:
                self._audio_chunks = chunks
        except Exception as e:
            print(f"[Client] Ошибка записи: {e}", file=sys.stderr, flush=True)
            _mac_log("error", "record_worker_error %s", e)

    def _start_recording(self) -> None:
        with self._lock:
            # Если уже идёт запись - не начинаем новую
            if self._recording:
                return
            # Если обработка идёт - всё равно разрешаем новую запись (как на Windows)
            # Старая обработка продолжит в фоне, но результат может быть проигнорирован
            self._recording = True
        self._stop_record.clear()
        self._audio_chunks.clear()
        self._paste_target_unix_id = None
        # Микрофон сразу — до любых afplay/osascript (иначе съедается первое слово).
        self._record_thread = threading.Thread(
            target=self._record_worker,
            name="whisper-record",
            daemon=True,
        )
        self._record_thread.start()
        _mac_log("info", "recording_started hotkey=%s", self._hotkey_label)

        def _snapshot_bg() -> None:
            self._paste_target_unix_id = self._snapshot_frontmost_unix_pid()

        threading.Thread(target=_snapshot_bg, name="whisper-paste-target", daemon=True).start()

        def _beep_async() -> None:
            try:
                subprocess.Popen(
                    ["afplay", "-v", "0.2", "/System/Library/Sounds/Pop.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                try:
                    print("\a", end="", flush=True)
                except Exception:
                    pass

        threading.Thread(target=_beep_async, name="whisper-beep", daemon=True).start()
        print(f"[Запись] Зажато {self._hotkey_label} — говори…", flush=True)

    def _stop_recording_and_process(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            self._busy = True
        self._stop_record.set()
        if self._record_thread is not None:
            self._record_thread.join(timeout=5.0)
            self._record_thread = None
        chunks = self._audio_chunks[:]
        self._audio_chunks.clear()

        if not chunks:
            print("[Client] Нет аудио.", flush=True)
            mac_banner_notification("Whisper", "Нет аудио — проверь микрофон и доступ.")
            self._reset_hotkey_tracker()
            with self._lock:
                self._busy = False
            return

        # Объединяем аудио
        audio_data = np.frombuffer(b"".join(chunks), dtype=np.float32)
        min_samples = int(0.25 * self.sample_rate)
        if audio_data.size < min_samples:
            print("[Client] Запись слишком короткая.", flush=True)
            mac_banner_notification("Whisper", "Запись слишком короткая — держи хоткей дольше.")
            self._reset_hotkey_tracker()
            with self._lock:
                self._busy = False
            return

        # Снимок до фонового потока — пока не началась следующая запись, PID цели стабилен для этой сессии.
        paste_target_pid = self._paste_target_unix_id

        def work() -> None:
            # Один поток обработки за раз — иначе два kick подряд убивают свежий Listener.
            with self._work_lock:
                with self._lock:
                    self._busy = True
                try:
                    _work_body(paste_target_pid)
                finally:
                    self._reset_hotkey_tracker()
                    with self._lock:
                        self._busy = False
                    self._schedule_listener_kick()

        def _work_body(paste_pid: int | None) -> None:
            try:
                # Сохраняем во временный WAV
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                    sf.write(tmp_path, audio_data, self.sample_rate)

                try:
                    if self._speaker_verify:
                        try:
                            from speaker_verify import (
                                SpeakerRejected,
                                load_reference,
                                verify_wav_file_or_raise,
                            )
                        except ImportError:
                            _mac_log("warning", "speaker_verify_no_module install requirements-speaker.txt")
                        else:
                            ref = load_reference()
                            if ref is None:
                                _mac_log(
                                    "warning",
                                    "speaker_verify_enabled_but_no_enrollment use --enroll-speaker",
                                )
                            else:
                                try:
                                    verify_wav_file_or_raise(
                                        tmp_path,
                                        thr_override=self._speaker_threshold,
                                    )
                                except SpeakerRejected as e:
                                    print(f"[Client] {e}", flush=True)
                                    _mac_log("info", "speaker_rejected %s", e)
                                    mac_banner_notification("Whisper", str(e)[:220])
                                    return

                    # Проверяем доступность сервера перед отправкой
                    try:
                        health_check = requests.get(f"{self.server_url}/", timeout=5.0)
                        if health_check.status_code != 200:
                            print(f"[Client] Сервер недоступен (код {health_check.status_code})", flush=True)
                            _mac_log(
                                "error",
                                "health_check status=%s url=%s",
                                health_check.status_code,
                                self.server_url,
                            )
                            raise ConnectionError("Сервер недоступен")
                    except requests.exceptions.RequestException as e:
                        print(f"[Client] Не удаётся подключиться к серверу: {e}", flush=True)
                        print(f"[Client] Проверь, что сервер запущен на {self.server_url}", flush=True)
                        _mac_log("error", "health_check_request_error %s url=%s", e, self.server_url)
                        raise

                    # Отправляем на сервер с повторными попытками
                    print("[Client] Отправка на сервер…", flush=True)
                    _mac_notify_progress("Отправка на сервер, жди ответ…")
                    _mac_log("info", "transcribe_upload_start url=%s paste_target_pid=%s", self.server_url, paste_pid)
                    max_retries = 3
                    response = None
                    try:
                        _tx_to = float(
                            (os.environ.get("WHISPER_MAC_TRANSCRIBE_TIMEOUT") or "300").strip() or "300"
                        )
                    except ValueError:
                        _tx_to = 300.0

                    for attempt in range(max_retries):
                        try:
                            with open(tmp_path, "rb") as f:
                                files = {"audio": ("audio.wav", f, "audio/wav")}
                                params = {}
                                if self.language:
                                    params["language"] = self.language
                                params["spoken_punctuation"] = str(self.spoken_punctuation).lower()

                                response = requests.post(
                                    f"{self.server_url}/transcribe",
                                    files=files,
                                    params=params,
                                    headers={"X-Whisper-Client": "mac"},
                                    timeout=_tx_to,
                                )
                                if response.status_code >= 400:
                                    detail = _fastapi_error_detail(response)
                                    _mac_log(
                                        "error",
                                        "transcribe_http status=%s detail=%r",
                                        response.status_code,
                                        detail,
                                    )
                                    if response.status_code == 403:
                                        mac_banner_notification("Whisper — отклонено", detail[:220])
                                    else:
                                        mac_banner_notification(
                                            "Whisper — ошибка сервера",
                                            f"{response.status_code}: {detail}"[:220],
                                        )
                                    return
                                break  # успешно, выходим из цикла
                        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                            if attempt < max_retries - 1:
                                wait_time = (attempt + 1) * 2
                                print(
                                    f"[Client] Ошибка соединения (попытка {attempt + 1}/{max_retries}), повтор через {wait_time} сек…",
                                    flush=True,
                                )
                                time.sleep(wait_time)
                            else:
                                print(f"[Client] Не удалось подключиться после {max_retries} попыток", flush=True)
                                raise

                    if response is None:
                        raise ConnectionError("Не удалось получить ответ от сервера")

                    try:
                        result = response.json()
                    except ValueError:
                        body = (response.text or "")[:400]
                        _mac_log("error", "transcribe_bad_json status=%s body_prefix=%r", response.status_code, body)
                        print("[Client] Ответ сервера не JSON — см. ~/Library/Logs/WhisperMacClient.log", flush=True)
                        mac_banner_notification("Whisper — ошибка", "Некорректный ответ сервера (не JSON).")
                        raise
                    text = result.get("text", "").strip()
                    _mac_log(
                        "info",
                        "transcribe_ok chars=%d preview=%r language=%r",
                        len(text),
                        text[:160],
                        result.get("language"),
                    )
                    if os.environ.get("WHISPER_MAC_DEBUG"):
                        _mac_log("debug", "transcribe_full_text=%r", text)

                    if text:
                        # Не даём synthetic release от Controller/osascript попасть в pressed — иначе hotkey ломается.
                        paste_ok = False
                        with self._hk_lock:
                            self._hk_suppress = True
                        try:
                            self._release_sticky_modifiers()
                            time.sleep(0.15)
                            if paste_pid is not None:
                                activated = self._activate_process_by_unix_id(paste_pid)
                                _mac_log(
                                    "info",
                                    "restore_focus pid=%s ok=%s",
                                    paste_pid,
                                    activated,
                                )
                            else:
                                _mac_log(
                                    "warning",
                                    "paste_target_pid_unknown — Cmd+V уйдёт в текущее frontmost-окно",
                                )
                            time.sleep(0.08)
                            self._copy_to_clipboard_mac(text)
                            time.sleep(0.06)
                            if self._clipboard_matches_expected(text):
                                _mac_log("info", "clipboard_ok after pbcopy (%d chars)", len(text))
                            else:
                                _mac_log(
                                    "warning",
                                    "clipboard_mismatch after pbcopy expected_prefix=%r got_preview=%r",
                                    text[:80],
                                    self._clipboard_preview(100),
                                )
                            time.sleep(0.12)
                            ok = self._paste_via_system_events()
                            paste_ok = bool(ok)
                            if ok:
                                print(f"[Client] Текст вставлен: {text[:60]}…", flush=True)
                                _mac_log("info", "paste_cmd_v_ok")
                            else:
                                pyperclip.copy(text)
                                print(
                                    f"[Client] Системная вставка не сработала (osascript). Текст в буфере: {text[:60]}…",
                                    flush=True,
                                )
                                print("[Client] Нажми Cmd+V в нужном поле.", flush=True)
                                _mac_log("warning", "paste_cmd_v_failed text_left_in_clipboard=yes")
                        except Exception as e:
                            try:
                                pyperclip.copy(text)
                            except Exception:
                                pass
                            print(f"[Client] Вставка не удалась ({e}), текст в буфере: {text[:60]}…", flush=True)
                            print("[Client] Нажми Cmd+V для вставки.", flush=True)
                            _MAC_LOGGER.error("paste_pipeline_error", exc_info=True)
                        finally:
                            self._reset_hotkey_tracker()
                        if os.environ.get("WHISPER_MAC_NOTIFY_SUCCESS", "1") != "0":
                            prev = text[:130] + ("…" if len(text) > 130 else "")
                            if paste_ok:
                                mac_banner_notification("Whisper — готово", prev)
                            else:
                                mac_banner_notification("Whisper — текст в буфере", prev + " — нажми Cmd+V.")
                    else:
                        print("[Client] Текст не распознан.", flush=True)
                        _mac_log("info", "transcribe_empty_text keys=%s", list(result.keys()))
                        mac_banner_notification(
                            "Whisper",
                            "Текст не распознан — говори громче или подольше.",
                        )
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
            except requests.exceptions.ConnectionError as e:
                print(f"[Client] Ошибка соединения с сервером: {e}", file=sys.stderr, flush=True)
                print(f"[Client] Убедись, что сервер запущен на {self.server_url}", file=sys.stderr, flush=True)
                print(f"[Client] Проверь Tailscale соединение и брандмауэр Windows", file=sys.stderr, flush=True)
                mac_banner_notification("Whisper — нет связи", f"Сервер недоступен: {self.server_url}")
            except requests.exceptions.Timeout as e:
                print(f"[Client] Таймаут при обработке (слишком долго)", file=sys.stderr, flush=True)
                print(f"[Client] Попробуй более короткую запись или проверь сервер", file=sys.stderr, flush=True)
                mac_banner_notification("Whisper — таймаут", "Сервер долго не отвечает — попробуй короче или проверь ПК.")
            except Exception as e:
                print(f"[Client] Ошибка: {e}", file=sys.stderr, flush=True)
                _MAC_LOGGER.exception("work_body_error")
                mac_banner_notification("Whisper — ошибка", str(e)[:200])
                import traceback

                traceback.print_exc()

        threading.Thread(target=work, name="whisper-transcribe", daemon=True).start()

    def run(self, *, menu_bar: bool = False) -> None:
        print(f"[Client] Удерживай {self._hotkey_label} — запись, отпусти все клавиши сочетания — распознавание.", flush=True)
        print(f"[Client] Сервер: {self.server_url}", flush=True)
        if menu_bar and rumps is not None:
            print("[Client] Иконка 🎤 в строке меню — «Выход» там же. Горячие клавиши без ⌘ (не трогаем Portal).", flush=True)
        else:
            print("[Client] Выход: Ctrl+C", flush=True)
        print(
            "[Client] Перехват клавиш в фоновом потоке с автоперезапуском (macOS / Portal / Cmd+V).",
            flush=True,
        )

        self._run_stop = False

        def _sigint(_signum: int, _frame: object | None) -> None:
            print("\n[Client] Остановка…", flush=True)
            self.request_shutdown()

        signal.signal(signal.SIGINT, _sigint)

        self._ensure_listener_thread()

        def _headless_main_loop() -> None:
            while not self._run_stop:
                self._ensure_listener_thread()
                t = self._listener_thread
                if t is not None:
                    t.join(timeout=0.6)

        try:
            if menu_bar and WhisperMenuBarApp is not None:
                try:
                    WhisperMenuBarApp(self).run()
                except BaseException:
                    _MAC_LOGGER.exception("rumps_menu_bar_crashed_fallback_headless")
                    try:
                        mac_banner_notification(
                            "Whisper",
                            "Строка меню недоступна — клиент работает без иконки. См. ~/Library/Logs/WhisperMacClient.log",
                        )
                    except Exception:
                        pass
                    _headless_main_loop()
            else:
                _headless_main_loop()
        finally:
            self.request_shutdown()
            if self._listener_thread is not None:
                self._listener_thread.join(timeout=5.0)


if rumps is not None:

    class WhisperMenuBarApp(rumps.App):
        """Индикатор в menu bar. Хоткей Whisper без ⌘ — не пересекается с Portal (⌘⌃P/C/V)."""

        def __init__(self, client: WhisperClientMac) -> None:
            ip = tray_icon_path()
            try:
                from whisper_version import get_version as _gv

                self._app_version = _gv()
            except ImportError:
                self._app_version = "?"
            if ip:
                super().__init__("Whisper", icon=ip, quit_button=None)
                self._emoji_mode = False
            else:
                super().__init__("Whisper", title="🎤", quit_button=None)
                self._emoji_mode = True
            self.client = client
            self._mi_server = rumps.MenuItem(self._server_title(), callback=None)
            self.menu = [
                rumps.MenuItem(f"Версия {self._app_version}", callback=None),
                self._mi_server,
                rumps.separator,
                rumps.MenuItem("Проверить обновления…", callback=self._check_updates_menu),
                rumps.MenuItem("Записать эталон голоса (45 с)…", callback=self._enroll_speaker_menu),
                rumps.separator,
                rumps.MenuItem("Показать лог…", callback=self._open_log),
                rumps.MenuItem("Выход", callback=self._quit),
            ]
            threading.Timer(12.0, self._startup_update_check_once).start()

        def _server_title(self) -> str:
            u = self.client.server_url
            return u if len(u) <= 56 else u[:53] + "…"

        def _open_log(self, _sender) -> None:
            logf = Path.home() / "Library" / "Logs" / "WhisperMacClient.log"
            if not logf.is_file():
                logf = Path(tempfile.gettempdir()) / "WhisperMacClient.log"
            subprocess.run(["open", "-R", str(logf)], check=False)

        def _check_updates_menu(self, _sender) -> None:
            threading.Thread(
                target=lambda: run_mac_update_flow(notify_always=True),
                name="whisper-mac-update",
                daemon=True,
            ).start()

        def _startup_update_check_once(self) -> None:
            if self.client._run_stop:
                return
            if os.environ.get("WHISPER_SKIP_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes"):
                return
            try:
                run_mac_update_flow(notify_newer_only=True)
            except Exception:
                _MAC_LOGGER.debug("startup_update_check", exc_info=True)

        def _enroll_speaker_menu(self, _sender) -> None:
            ok = rumps.alert(
                title="Эталон голоса",
                message="После «Начать» пойдёт запись 45 секунд.\n\nГовори в обычном темпе одним голосом. Рядом не должно болтать других людей.\n\nНужны пакеты torch + resemblyzer (см. инструкцию HTML, один раз в Терминале).",
                ok="Начать",
                cancel="Отмена",
            )
            if ok != 1:
                return
            threading.Thread(target=self._enroll_record_worker, name="whisper-enroll", daemon=True).start()

        def _enroll_record_worker(self) -> None:
            sr = 16000
            dur_sec = 45
            frames = int(sr * dur_sec)
            tmp_path: str | None = None
            try:
                try:
                    from speaker_verify import embedding_path, enroll_from_wav
                except ImportError:
                    mac_banner_notification(
                        "Whisper",
                        "Нет модулей для эталона. Один раз в Терминале: python3 -m pip install torch resemblyzer",
                    )
                    return
                mac_banner_notification("Whisper", "Идёт запись 45 с — говори в микрофон…")
                rec = sd.rec(frames, samplerate=sr, channels=1, dtype="float32")
                sd.wait()
                flat = np.asarray(rec).reshape(-1)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    tmp_path = tf.name
                sf.write(tmp_path, flat, sr)
                enroll_from_wav(tmp_path)
                self.client._speaker_verify = True
                _mac_log("info", "enroll_menu_ok path=%s", embedding_path())
                mac_banner_notification(
                    "Whisper",
                    "Эталон сохранён. Проверка голоса включена для этой сессии; при следующем запуске .app — автоматически.",
                )
            except Exception as e:
                _MAC_LOGGER.exception("enroll_menu_failed")
                mac_banner_notification("Whisper", f"Ошибка записи эталона: {e!s:.120}")
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

        def _quit(self, _sender) -> None:
            self.client.request_shutdown()
            if self.client._listener_thread and self.client._listener_thread.is_alive():
                self.client._listener_thread.join(timeout=5.0)
            rumps.quit_application()

        @rumps.timer(0.5)
        def _tick(self, _sender) -> None:
            if self.client._run_stop:
                rumps.quit_application()
                return
            self._mi_server.title = self._server_title()
            if not self._emoji_mode:
                return
            rec = busy = False
            with self.client._lock:
                rec = self.client._recording
                busy = self.client._busy
            self.title = "🔴" if (rec or busy) else "🎤"

        @rumps.timer(2.0)
        def _watchdog_listener(self, _sender) -> None:
            if self.client._run_stop:
                return
            self.client._ensure_listener_thread()

else:
    WhisperMenuBarApp = None  # type: ignore[misc, assignment]


def main() -> int:
    log_path = configure_whisper_mac_logging()
    _mac_log("info", "=== старт whisper-client-mac ===")
    try:
        _check_pynput_py313()
    except SystemExit as e:
        if e.code not in (0, None):
            _mac_log("error", "pynput_version_check_exit code=%s", e.code)
        raise

    if hasattr(threading, "excepthook"):
        _orig_thread_excepthook = threading.excepthook

        def _thread_excepthook(args: object) -> None:
            th = getattr(args, "thread", None)
            exc_t = getattr(args, "exc_type", None)
            exc_v = getattr(args, "exc_value", None)
            exc_tb = getattr(args, "exc_traceback", None)
            _MAC_LOGGER.error(
                "thread_crash name=%s",
                getattr(th, "name", "?"),
                exc_info=(exc_t, exc_v, exc_tb) if exc_t else None,
            )
            _orig_thread_excepthook(args)

        threading.excepthook = _thread_excepthook  # type: ignore[method-assign]

    # macOS при запуске .app из Finder добавляет -psn_0_… в argv; иначе parse_args() падает и приложение сразу завершается.
    sys.argv = [sys.argv[0]] + [
        a for a in sys.argv[1:] if not a.startswith("-psn_")
    ]

    p = argparse.ArgumentParser(
        description="Whisper клиент для Mac",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
В терминале при старте (если не указан --hotkey) спросит сочетание; Enter = ⌃+⇧+⌥.
Примеры:
  %(prog)s --server URL
  %(prog)s --server URL --hotkey shift+ctrl+grave
  %(prog)s --server URL --no-hotkey-prompt   # без вопроса, ⌃+⇧+⌥ (или WHISPER_MAC_HOTKEY)
  %(prog)s --server URL --bind-hotkey
        """.strip(),
    )
    p.add_argument(
        "--server",
        default=None,
        help="URL сервера (например: http://192.168.1.100:8000); не нужен только с --enroll-speaker",
    )
    p.add_argument("--language", default=None, help="ru, en или авто")
    p.add_argument(
        "--no-spoken-punctuation",
        action="store_true",
        help="Не заменять «запятая» на знаки",
    )
    p.add_argument(
        "--hotkey",
        default=None,
        metavar="COMBO",
        help="Сочетание через +: alt+ctrl, cmd+alt, ctrl+grave … (без флага — спросит в терминале)",
    )
    p.add_argument(
        "--no-hotkey-prompt",
        action="store_true",
        help="Не спрашивать сочетание в терминале; без --hotkey — ⌃+⇧+⌥ или WHISPER_MAC_HOTKEY",
    )
    p.add_argument(
        "--bind-hotkey",
        action="store_true",
        help="Зажми сочетание и отпусти — запомнить (вместо строки и промпта)",
    )
    p.add_argument(
        "--bind-timeout",
        type=float,
        default=90.0,
        metavar="SEC",
        help="Секунд ожидания при --bind-hotkey (по умолчанию 90)",
    )
    p.add_argument(
        "--no-menu-bar",
        action="store_true",
        help="Не показывать иконку в строке меню (нужен пакет rumps; см. README)",
    )
    p.add_argument(
        "--enroll-speaker",
        metavar="WAV",
        default=None,
        help="Сохранить эталон голоса из WAV (~30–60 с); нужен pip install -r requirements-speaker.txt",
    )
    p.add_argument(
        "--speaker-verify",
        action="store_true",
        help="Перед отправкой на сервер сверять голос с эталоном (~/.whisper/speaker_embedding.npy)",
    )
    p.add_argument(
        "--speaker-threshold",
        type=float,
        default=None,
        metavar="0.0-1.0",
        help="Порог косинусного сходства (по умолчанию из WHISPER_SPEAKER_THRESHOLD или 0.72)",
    )
    args = p.parse_args()

    if not args.enroll_speaker and not args.server:
        p.error("нужен --server (или только --enroll-speaker WAV для эталона голоса)")

    if args.enroll_speaker:
        try:
            from speaker_verify import embedding_path, enroll_from_wav
        except ImportError:
            print(
                "[Client] Нет speaker_verify — установи: pip install -r requirements-speaker.txt",
                file=sys.stderr,
            )
            return 1
        try:
            enroll_from_wav(args.enroll_speaker)
            print(f"[Client] Эталон сохранён: {embedding_path()}", flush=True)
            return 0
        except Exception as e:
            print(f"[Client] enroll-speaker: {e}", file=sys.stderr)
            return 1

    try:
        from whisper_version import get_version as _app_ver

        _mac_log("info", "app_version=%s", _app_ver())
    except ImportError:
        pass

    _mac_log("info", "server=%s log_file=%s", args.server, log_path)
    if not sys.stdout.isatty():
        print(f"[Client] Подробный лог: {log_path}", flush=True)

    def _default_hotkey_str() -> str:
        raw = (os.environ.get("WHISPER_MAC_HOTKEY") or "").strip()
        return raw if raw else "shift+ctrl+alt"

    def read_hotkey_from_terminal() -> HotkeySpec:
        dflt = _default_hotkey_str()
        print(
            "[Client] Сочетание задаётся ТЕКСТОМ (латиницей), не путай с физическим нажатием клавиш в другом окне.",
            flush=True,
        )
        print(
            "[Client] Примеры:  shift+ctrl+alt   shift+ctrl+grave   alt+ctrl   ctrl+grave   shift+ctrl+rbracket",
            flush=True,
        )
        print(
            f"[Client] Пустой Enter = по умолчанию ({dflt}; задай WHISPER_MAC_HOTKEY или --hotkey чтобы поменять).",
            flush=True,
        )
        print(
            "[Client] Чтобы задать сочетание одним нажатием клавиш, закрой и запусти с флагом  --bind-hotkey",
            flush=True,
        )
        try:
            line = input("[Client] Строка сочетания: ").strip()
        except EOFError:
            line = ""
        if not line:
            return parse_hotkey_string(dflt)
        return parse_hotkey_string(line)

    try:
        if args.bind_hotkey:
            hotkey = bind_hotkey_interactive(timeout=args.bind_timeout)
        elif args.hotkey is not None:
            hotkey = parse_hotkey_string(args.hotkey)
        elif args.no_hotkey_prompt or not sys.stdin.isatty():
            hotkey = parse_hotkey_string(_default_hotkey_str())
        else:
            hotkey = read_hotkey_from_terminal()
    except ValueError as e:
        print(f"[Client] Ошибка горячей клавиши: {e}", file=sys.stderr)
        return 2

    print(f"[Client] Активное сочетание: {describe_hotkey(hotkey)}", flush=True)

    if os.environ.get("WHISPER_FROM_APP_BUNDLE"):
        subprocess.run(
            [
                "logger",
                "-t",
                "WhisperClient",
                "Старт pid=%s server=%s hotkey=%s"
                % (os.getpid(), args.server, describe_hotkey(hotkey)),
            ],
            check=False,
        )
        if not sys.stdin.isatty():
            hk = describe_hotkey(hotkey)
            mac_banner_notification(
                "Whisper Client",
                f"Клиент в фоне. Удерживай {hk} — запись; отпусти все клавиши сочетания — распознавание.",
            )

    use_menu_bar = (
        sys.platform == "darwin"
        and WhisperMenuBarApp is not None
        and not args.no_menu_bar
        and os.environ.get("WHISPER_MAC_NO_MENU") != "1"
    )
    if (
        os.environ.get("WHISPER_FROM_APP_BUNDLE")
        and sys.platform == "darwin"
        and WhisperMenuBarApp is None
        and not args.no_menu_bar
    ):
        print(
            "[Client] Иконка в строке меню: pip install rumps (тем же python3, что запускает клиент).",
            flush=True,
        )
        exe = sys.executable.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display dialog "Нет пакета rumps — не будет иконки 🎤 в строке меню.\\n\\nВыполни в Терминале:\\n{exe} -m pip install rumps" '
                'buttons {"OK"} default button 1 with title "Whisper Client"',
            ],
            check=False,
            capture_output=True,
        )
        _mac_log("warning", "rumps_missing executable=%s", sys.executable)

    _mac_log(
        "info",
        "runtime python=%s rumps_ok=%s menu_bar_requested=%s",
        sys.executable,
        rumps is not None,
        (
            sys.platform == "darwin"
            and rumps is not None
            and not args.no_menu_bar
            and os.environ.get("WHISPER_MAC_NO_MENU") != "1"
        ),
    )

    if os.environ.get("WHISPER_MAC_NO_SPEAKER_VERIFY", "").strip() == "1":
        spk = False
    else:
        spk = args.speaker_verify or (
            os.environ.get("WHISPER_SPEAKER_VERIFY", "").strip().lower() in ("1", "true", "yes")
        )
    client = WhisperClientMac(
        server_url=args.server,
        language=args.language,
        spoken_punctuation=not args.no_spoken_punctuation,
        hotkey=hotkey,
        speaker_verify=spk,
        speaker_threshold=args.speaker_threshold,
    )
    try:
        client.run(menu_bar=use_menu_bar)
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
