#!/usr/bin/env python3
"""
Клиент для Mac: запись с микрофона, отправка на Windows-сервер, вставка текста.
Запуск: python3 whisper-client-mac.py --server http://192.168.1.100:8000
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import requests
    import sounddevice as sd
    import numpy as np
    import soundfile as sf
    from pynput import keyboard
    import pyperclip
except ImportError as e:
    print(f"Ошибка импорта: {e}", file=sys.stderr)
    print("Установи: pip3 install requests sounddevice numpy soundfile pynput pyperclip", file=sys.stderr)
    sys.exit(1)


class WhisperClientMac:
    def __init__(self, server_url: str, language: str | None = None, spoken_punctuation: bool = True):
        self.server_url = server_url.rstrip("/")
        self.language = language
        self.spoken_punctuation = spoken_punctuation
        self.sample_rate = 16000
        self.channels = 1
        self._lock = threading.Lock()
        self._recording = False
        self._last_combo = False
        self._stop_record = threading.Event()
        self._record_thread: threading.Thread | None = None
        self._audio_chunks: list[bytes] = []
        self._busy = False


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
            if self._recording or self._busy:
                if self._busy:
                    print("[Client] Обработка предыдущей записи, пропуск.", flush=True)
                return
            self._recording = True
        self._stop_record.clear()
        self._audio_chunks.clear()
        # Звуковой сигнал (через системный beep на Mac)
        import subprocess
        try:
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False, timeout=1.0)
        except Exception:
            print("\a", end="", flush=True)  # Fallback: ASCII bell
        print("[Запись] Зажато Cmd+Option — говори…", flush=True)
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
            with self._lock:
                self._busy = False
            return

        # Объединяем аудио
        audio_data = np.frombuffer(b"".join(chunks), dtype=np.float32)
        min_samples = int(0.25 * self.sample_rate)
        if audio_data.size < min_samples:
            print("[Client] Запись слишком короткая.", flush=True)
            with self._lock:
                self._busy = False
            return

        def work() -> None:
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
                                    timeout=180.0,  # увеличил таймаут до 3 минут
                                )
                                response.raise_for_status()
                                break  # успешно, выходим из цикла
                        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                            if attempt < max_retries - 1:
                                wait_time = (attempt + 1) * 2
                                print(f"[Client] Ошибка соединения (попытка {attempt + 1}/{max_retries}), повтор через {wait_time} сек…", flush=True)
                                time.sleep(wait_time)
                            else:
                                print(f"[Client] Не удалось подключиться после {max_retries} попыток", flush=True)
                                raise
                    
                    if response is None:
                        raise ConnectionError("Не удалось получить ответ от сервера")
                    
                    result = response.json()
                    text = result.get("text", "").strip()

                    if text:
                            # Копируем в буфер обмена и вставляем через Cmd+V
                            try:
                                import pyperclip
                                pyperclip.copy(text)
                                # Вставляем через Cmd+V
                                import subprocess
                                subprocess.run(
                                    ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
                                    check=False,
                                    timeout=2.0,
                                )
                                print(f"[Client] Текст вставлен: {text[:60]}…", flush=True)
                            except Exception as e:
                                # Fallback: только буфер обмена
                                print(f"[Client] Вставка не удалась, текст в буфере обмена: {text[:60]}…", flush=True)
                                print("[Client] Нажми Cmd+V для вставки.", flush=True)
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
                print(f"[Client] Убедись, что сервер запущен на {self.server_url}", flush=True)
                print(f"[Client] Проверь Tailscale соединение и брандмауэр Windows", flush=True)
            except requests.exceptions.Timeout as e:
                print(f"[Client] Таймаут при обработке (слишком долго)", file=sys.stderr, flush=True)
                print(f"[Client] Попробуй более короткую запись или проверь сервер", flush=True)
            except Exception as e:
                print(f"[Client] Ошибка: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc()
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def run(self) -> None:
        print("[Client] Зажми Cmd+Option — запись, отпусти — распознавание.", flush=True)
        print(f"[Client] Сервер: {self.server_url}", flush=True)
        print("[Client] Выход: Ctrl+C", flush=True)

        # Отслеживаем комбинацию Cmd+Option (⌘⌥)
        pressed_keys = set()

        def on_press(key):
            try:
                # Определяем какая клавиша нажата
                is_cmd = False
                is_alt = False
                
                # Проверяем через атрибуты key
                if key == keyboard.Key.cmd_l or key == keyboard.Key.cmd_r:
                    is_cmd = True
                elif key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
                    is_alt = True
                else:
                    # Проверяем через name/value
                    key_str = ""
                    if hasattr(key, 'name') and key.name:
                        key_str = str(key.name).lower()
                    elif hasattr(key, 'value'):
                        key_str = str(key.value).lower()
                    
                    if 'cmd' in key_str:
                        is_cmd = True
                    elif 'alt' in key_str or 'option' in key_str:
                        is_alt = True
                
                if is_cmd:
                    pressed_keys.add("cmd")
                elif is_alt:
                    pressed_keys.add("alt")
                
                # Если обе клавиши зажаты и запись ещё не началась
                if "cmd" in pressed_keys and "alt" in pressed_keys:
                    if not self._last_combo:
                        self._start_recording()
                        self._last_combo = True
            except Exception:
                pass

        def on_release(key):
            try:
                # Определяем какая клавиша отпущена
                is_cmd = False
                is_alt = False
                
                if key == keyboard.Key.cmd_l or key == keyboard.Key.cmd_r:
                    is_cmd = True
                elif key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
                    is_alt = True
                else:
                    key_str = ""
                    if hasattr(key, 'name') and key.name:
                        key_str = str(key.name).lower()
                    elif hasattr(key, 'value'):
                        key_str = str(key.value).lower()
                    
                    if 'cmd' in key_str:
                        is_cmd = True
                    elif 'alt' in key_str or 'option' in key_str:
                        is_alt = True
                
                if is_cmd:
                    pressed_keys.discard("cmd")
                elif is_alt:
                    pressed_keys.discard("alt")
                
                # Если комбинация больше не зажата и запись была активна
                if not ("cmd" in pressed_keys and "alt" in pressed_keys):
                    if self._last_combo:
                        self._stop_recording_and_process()
                        self._last_combo = False
            except Exception:
                pass

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            try:
                listener.join()
            except KeyboardInterrupt:
                print("\n[Client] Остановка…", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Whisper клиент для Mac")
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
    args = p.parse_args()

    client = WhisperClientMac(
        server_url=args.server,
        language=args.language,
        spoken_punctuation=not args.no_spoken_punctuation,
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
