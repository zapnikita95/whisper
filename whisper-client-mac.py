#!/usr/bin/env python3
"""
Клиент для Mac: запись с микрофона, отправка на Windows-сервер, вставка текста.
Запуск: python3 whisper-client-mac.py --server http://192.168.1.100:8000
Горячая клавиша: при запуске в терминале спросит строку (Enter = ⌃+⇧+`), либо --hotkey, либо --bind-hotkey

Рядом с Portal (⌘+⌃+P/C/V): по умолчанию ⌃+⇧+` — не трогает Cmd и не совпадает с хоткеями Портала.
Переопределение: переменная WHISPER_MAC_HOTKEY (например shift+ctrl+]) или флаг --hotkey.
См. PORTAL_AND_WHISPER_MAC.md
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
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


_check_pynput_py313()


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
        """⌃+⇧+` — не пересекается с Portal (⌘+⌃+P / C / V)."""
        return HotkeySpec(frozenset({"m:shift", "m:ctrl", "c:`"}))

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
    print("[Client] Таймаут привязки — остаётся ⌃+⇧+` (shift+ctrl+grave).", flush=True)
    return HotkeySpec.default_mac_with_portal()


class WhisperClientMac:
    def __init__(
        self,
        server_url: str,
        language: str | None = None,
        spoken_punctuation: bool = True,
        hotkey: HotkeySpec | None = None,
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
        self._run_stop = False
        self._work_lock = threading.Lock()

    def _reset_hotkey_tracker(self) -> None:
        """Сброс модели «какие клавиши зажаты» — после вставки и после цикла распознавания."""
        with self._hk_lock:
            self._hk_suppress = False
            self._hk_pressed.clear()
            self._hk_combo_active = False

    def _kick_listener_restart(self, *, force: bool = False) -> None:
        """Останавливает текущий Listener; run() сразу поднимет новый (новый event tap)."""
        if not force and self._run_stop:
            return
        lr = self._listener_ref
        if lr is not None:
            try:
                lr.stop()
            except Exception:
                pass

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

    def _paste_via_system_events(self) -> bool:
        """Cmd+V через key code 9 (клавиша V), без keystroke — стабильнее при разных раскладках."""
        r = subprocess.run(
            [
                "osascript",
                "-e",
                "delay 0.12",
                "-e",
                'tell application "System Events" to key code 9 using command down',
            ],
            capture_output=True,
            text=True,
            timeout=3.0,
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
        # Звуковой сигнал (через системный beep на Mac)
        try:
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False, timeout=1.0)
        except Exception:
            print("\a", end="", flush=True)  # Fallback: ASCII bell
        print(f"[Запись] Зажато {self._hotkey_label} — говори…", flush=True)
        self._record_thread = threading.Thread(target=self._record_worker, daemon=True)
        self._record_thread.start()

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
            self._reset_hotkey_tracker()
            with self._lock:
                self._busy = False
            return

        # Объединяем аудио
        audio_data = np.frombuffer(b"".join(chunks), dtype=np.float32)
        min_samples = int(0.25 * self.sample_rate)
        if audio_data.size < min_samples:
            print("[Client] Запись слишком короткая.", flush=True)
            self._reset_hotkey_tracker()
            with self._lock:
                self._busy = False
            return

        def work() -> None:
            # Один поток обработки за раз — иначе два kick подряд убивают свежий Listener.
            with self._work_lock:
                with self._lock:
                    self._busy = True
                try:
                    _work_body()
                finally:
                    self._reset_hotkey_tracker()
                    with self._lock:
                        self._busy = False
                    self._kick_listener_restart()

        def _work_body() -> None:
            try:
                # Сохраняем во временный WAV
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                    sf.write(tmp_path, audio_data, self.sample_rate)

                try:
                    # Проверяем доступность сервера перед отправкой
                    try:
                        health_check = requests.get(f"{self.server_url}/", timeout=5.0)
                        if health_check.status_code != 200:
                            print(f"[Client] Сервер недоступен (код {health_check.status_code})", flush=True)
                            raise ConnectionError("Сервер недоступен")
                    except requests.exceptions.RequestException as e:
                        print(f"[Client] Не удаётся подключиться к серверу: {e}", flush=True)
                        print(f"[Client] Проверь, что сервер запущен на {self.server_url}", flush=True)
                        raise

                    # Отправляем на сервер с повторными попытками
                    print("[Client] Отправка на сервер…", flush=True)
                    max_retries = 3
                    response = None

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
                                    timeout=180.0,  # увеличил таймаут до 3 минут
                                )
                                response.raise_for_status()
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

                    result = response.json()
                    text = result.get("text", "").strip()

                    if text:
                        # Не даём synthetic release от Controller/osascript попасть в pressed — иначе hotkey ломается.
                        with self._hk_lock:
                            self._hk_suppress = True
                        try:
                            self._release_sticky_modifiers()
                            time.sleep(0.15)
                            self._copy_to_clipboard_mac(text)
                            time.sleep(0.12)
                            ok = self._paste_via_system_events()
                            if ok:
                                print(f"[Client] Текст вставлен: {text[:60]}…", flush=True)
                            else:
                                pyperclip.copy(text)
                                print(
                                    f"[Client] Системная вставка не сработала (osascript). Текст в буфере: {text[:60]}…",
                                    flush=True,
                                )
                                print("[Client] Нажми Cmd+V в нужном поле.", flush=True)
                        except Exception as e:
                            try:
                                pyperclip.copy(text)
                            except Exception:
                                pass
                            print(f"[Client] Вставка не удалась ({e}), текст в буфере: {text[:60]}…", flush=True)
                            print("[Client] Нажми Cmd+V для вставки.", flush=True)
                        finally:
                            self._reset_hotkey_tracker()
                    else:
                        print("[Client] Текст не распознан.", flush=True)
                finally:
                    try:
                        import os

                        os.unlink(tmp_path)
                    except Exception:
                        pass
            except requests.exceptions.ConnectionError as e:
                print(f"[Client] Ошибка соединения с сервером: {e}", file=sys.stderr, flush=True)
                print(f"[Client] Убедись, что сервер запущен на {self.server_url}", file=sys.stderr, flush=True)
                print(f"[Client] Проверь Tailscale соединение и брандмауэр Windows", file=sys.stderr, flush=True)
            except requests.exceptions.Timeout as e:
                print(f"[Client] Таймаут при обработке (слишком долго)", file=sys.stderr, flush=True)
                print(f"[Client] Попробуй более короткую запись или проверь сервер", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[Client] Ошибка: {e}", file=sys.stderr, flush=True)
                import traceback

                traceback.print_exc()

        threading.Thread(target=work, daemon=True).start()

    def run(self) -> None:
        print(f"[Client] Удерживай {self._hotkey_label} — запись, отпусти все клавиши сочетания — распознавание.", flush=True)
        print(f"[Client] Сервер: {self.server_url}", flush=True)
        print("[Client] Выход: Ctrl+C", flush=True)
        print(
            "[Client] После каждой вставки перехват клавиш перезапускается (обход глюка macOS).",
            flush=True,
        )

        target = self.hotkey.tokens
        self._run_stop = False

        def on_press(key):
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
                pass

        def on_release(key):
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
                pass

        try:
            while not self._run_stop:
                with keyboard.Listener(
                    on_press=on_press,
                    on_release=on_release,
                    suppress=False,
                ) as listener:
                    self._listener_ref = listener
                    try:
                        listener.join()
                    finally:
                        self._listener_ref = None
        except KeyboardInterrupt:
            self._run_stop = True
            print("\n[Client] Остановка…", flush=True)
        finally:
            self._run_stop = True
            self._kick_listener_restart(force=True)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Whisper клиент для Mac",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
В терминале при старте (если не указан --hotkey) спросит сочетание; Enter = ⌥+⌃.
Примеры:
  %(prog)s --server URL
  %(prog)s --server URL --hotkey ctrl+grave
  %(prog)s --server URL --no-hotkey-prompt   # без вопроса, ⌃+⇧+` (или WHISPER_MAC_HOTKEY)
  %(prog)s --server URL --bind-hotkey
        """.strip(),
    )
    p.add_argument(
        "--server",
        required=True,
        help="URL сервера (например: http://192.168.1.100:8000)",
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
        help="Не спрашивать сочетание в терминале; без --hotkey — ⌃+⇧+` или WHISPER_MAC_HOTKEY",
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
    args = p.parse_args()

    def _default_hotkey_str() -> str:
        raw = (os.environ.get("WHISPER_MAC_HOTKEY") or "").strip()
        return raw if raw else "shift+ctrl+grave"

    def read_hotkey_from_terminal() -> HotkeySpec:
        dflt = _default_hotkey_str()
        print(
            "[Client] Сочетание задаётся ТЕКСТОМ (латиницей), не нажимай здесь физические ⌃⇧` — в терминале это не то же самое.",
            flush=True,
        )
        print(
            "[Client] Примеры:  shift+ctrl+grave   alt+ctrl   ctrl+grave   cmd+alt+period",
            flush=True,
        )
        print(
            f"[Client] Пустой Enter = по умолчанию ({dflt}; задай WHISPER_MAC_HOTKEY чтобы поменять).",
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

    client = WhisperClientMac(
        server_url=args.server,
        language=args.language,
        spoken_punctuation=not args.no_spoken_punctuation,
        hotkey=hotkey,
    )
    try:
        client.run()
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
