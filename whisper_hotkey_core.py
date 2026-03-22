"""

Глобальная комбинация: зажми Ctrl+Win — идёт запись, отпусти — распознавание и вставка текста.

Звук при начале записи. Слова «запятая», «точка» и т.д. превращаются в знаки препинания.

"""

from __future__ import annotations



import ctypes

import os

import re

import site

import sys

import tempfile

import logging

import threading

import time

from pathlib import Path

from collections.abc import Callable


log = logging.getLogger("whisper.hotkey")



try:

    import keyboard

    import pyperclip

    import numpy as np

    try:

        import pyaudio

        _USE_PYAUDIO = True

    except ImportError:

        try:

            import sounddevice as sd

            _USE_PYAUDIO = False

        except ImportError:

            print("Ошибка: нужен pyaudio или sounddevice", file=sys.stderr)

            print("Установи: pip install pyaudio", file=sys.stderr)

            sys.exit(1)

except ImportError as e:

    print(f"Ошибка импорта: {e}", file=sys.stderr)

    print("Установи зависимости: pip install keyboard pyaudio pyperclip pywin32", file=sys.stderr)

    sys.exit(1)





def _prepend_nvidia_cublas_to_path() -> bool:

    if sys.platform != "win32":

        return True

    candidates: list[Path] = []

    if getattr(sys, "frozen", False):

        exe_dir = Path(sys.executable).resolve().parent

        meip = getattr(sys, "_MEIPASS", None)

        if meip:

            candidates.append(Path(meip))

        candidates.append(exe_dir / "_internal")

        candidates.append(exe_dir)

    try:

        candidates.append(Path(site.getusersitepackages()))

    except Exception:

        pass

    try:

        candidates.extend(Path(p) for p in site.getsitepackages())

    except Exception:

        pass

    seen: set[Path] = set()

    for base in candidates:

        if not base or base in seen:

            continue

        seen.add(base.resolve())

        bin_dir = base / "nvidia" / "cublas" / "bin"

        if (bin_dir / "cublas64_12.dll").is_file():

            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

            return True

    return False


def _transcribe_timeout_sec_default() -> float:

    raw = (os.environ.get("WHISPER_HOTKEY_TRANSCRIBE_TIMEOUT") or "").strip()

    if not raw:

        return 300.0

    try:

        return max(30.0, min(float(raw), 3600.0))

    except ValueError:

        return 300.0





def _play_record_start_sound() -> None:

    if sys.platform == "win32":

        try:

            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)

        except Exception:

            try:

                import winsound

                winsound.Beep(880, 35)

            except Exception:

                pass





def apply_spoken_punctuation(text: str) -> str:

    """

    Заменяет произнесённые названия знаков на сами знаки (русский текст от Whisper).

    Порядок: сначала многословные фразы.

    """

    if not text:

        return text

    t = text

    pairs: list[tuple[str, str]] = [

        (r"восклицательный\s+знак", "!"),

        (r"вопросительный\s+знак", "?"),

        (r"запятая", ","),

        (r"точка", "."),

        (r"тире", "—"),

    ]

    flags = re.IGNORECASE

    for pattern, repl in pairs:

        t = re.sub(rf"(?iu)\b(?:{pattern})\b", repl, t)

    # пробелы вокруг знаков

    t = re.sub(r"\s*,\s*", ", ", t)

    t = re.sub(r"\s*\.\s*", ". ", t)

    t = re.sub(r"\s*!\s*", "! ", t)

    t = re.sub(r"\s*\?\s*", "? ", t)

    t = re.sub(r"\s*—\s*", " — ", t)

    t = re.sub(r"\s{2,}", " ", t).strip()

    return t





# Фразы-галлюцинации, которые Whisper выдаёт на тишину или шум
_HALLUCINATIONS: set[str] = {
    "thank you.", "thank you", "thanks for watching.", "thanks for watching",
    "you", "bye.", "bye",
    "спасибо.", "спасибо", "спасибо за просмотр.", "спасибо за просмотр",
    "до свидания.", "до свидания",
    "субтитры создавались в студии", "субтитры создавались в сту",
    ".", "..", "...", "…",
}


def _filter_hallucinations(text: str) -> str:
    """Убирает типичные галлюцинации Whisper на тишину/шум."""
    if text.lower() in _HALLUCINATIONS:
        return ""
    return text


def _win32_paste_once() -> None:
    """Один Ctrl+V через user32.keybd_event — без дублей от библиотеки keyboard."""
    VK_CONTROL = 0x11
    VK_V = 0x56
    KEYEVENTF_KEYUP = 0x0002
    u = ctypes.windll.user32
    u.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.02)
    u.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.02)
    u.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.02)
    u.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


class WhisperHotkey:

    def __init__(

        self,

        model: str = "large-v3",

        device: str = "cuda",

        compute_type: str = "int8",

        language: str | None = None,

        sample_rate: int = 16000,

        channels: int = 1,

        max_hold_seconds: float = 120.0,

        spoken_punctuation: bool = True,

        status_callback: Callable[[str], None] | None = None,

        toast_callback: Callable[[str, str, bool], None] | None = None,

        speaker_verify: bool = False,

        speaker_threshold: float | None = None,

    ):

        self.model_name = model

        self.device = device

        self.compute_type = compute_type

        self.language = language

        self.sample_rate = sample_rate

        self.channels = channels

        self.max_hold_seconds = max_hold_seconds

        self.spoken_punctuation = spoken_punctuation

        self._status_callback = status_callback

        self._toast_callback = toast_callback

        self.model = None

        self._lock = threading.Lock()

        self._busy = False

        self._hold_recording = False

        self._last_combo = False

        self._stop_record = threading.Event()

        self._cancel_processing = threading.Event()  # флаг для отмены текущей обработки

        self._record_thread: threading.Thread | None = None

        self._audio_chunks: list[bytes] = []

        self._chunk_lock = threading.Lock()

        self._insert_lock = threading.Lock()

        self._mic_fail_toast_ok = True

        self._speaker_verify = speaker_verify

        self._speaker_threshold = speaker_threshold

        self._transcribe_timeout_sec = _transcribe_timeout_sec_default()



    def _emit_status(self, msg: str) -> None:

        cb = self._status_callback

        if cb is None:

            return

        try:

            cb(msg)

        except Exception:

            pass



    def _emit_toast(self, title: str, body: str, error: bool = False) -> None:

        cb = self._toast_callback

        if cb is None:

            return

        try:

            cb(title, body, error)

        except Exception:

            pass



    def _combo_pressed(self) -> bool:

        try:

            ctrl = keyboard.is_pressed("ctrl")

            win = (

                keyboard.is_pressed("left windows")

                or keyboard.is_pressed("right windows")

                or keyboard.is_pressed("windows")

            )

            return ctrl and win

        except Exception:

            return False



    def _load_model(self) -> None:

        if self.model is not None:

            return

        cublas_ok = _prepend_nvidia_cublas_to_path()

        if (

            sys.platform == "win32"

            and str(self.device).lower() == "cuda"

            and not cublas_ok

        ):

            log.warning(

                "cuBLAS: cublas64_12.dll не найдена в site-packages. "

                "Поставь в venv: pip install nvidia-cublas-cu12 — иначе CTranslate2 часто не поднимет GPU."

            )

        from faster_whisper import WhisperModel



        print(f"[Whisper] Загрузка модели {self.model_name}...", flush=True)

        log.info("Загрузка модели %s (%s, %s)", self.model_name, self.device, self.compute_type)

        try:

            self.model = WhisperModel(

                self.model_name,

                device=self.device,

                compute_type=self.compute_type,

            )

        except OSError as e:

            log.exception("Модель: OSError")

            self._emit_toast(

                "Сеть или диск",

                "Не удалось загрузить модель (сеть, Hugging Face или место на диске).",

                True,

            )

            raise

        except Exception as e:

            log.exception("Модель: ошибка")

            self._emit_toast(

                "Модель",

                f"Не удалось загрузить веса: {type(e).__name__}",

                True,

            )

            raise

        print("[Whisper] Модель загружена.", flush=True)

        log.info("Модель загружена")



    def _record_worker(self) -> None:

        if not _USE_PYAUDIO:

            print("[Ошибка] Удержание записи поддерживается только с pyaudio.", file=sys.stderr, flush=True)

            return

        p = pyaudio.PyAudio()

        stream = None

        try:

            try:

                stream = p.open(

                    format=pyaudio.paFloat32,

                    channels=self.channels,

                    rate=self.sample_rate,

                    input=True,

                    frames_per_buffer=1024,

                )

            except OSError as e:

                log.exception("Микрофон недоступен")

                print(f"[Ошибка] Микрофон: {e}", file=sys.stderr, flush=True)

                with self._lock:

                    show = self._mic_fail_toast_ok

                    if show:

                        self._mic_fail_toast_ok = False

                if show:

                    self._emit_toast(

                        "Микрофон",

                        "Нет доступа к микрофону, устройство занято или не найдено.",

                        True,

                    )

                with self._lock:

                    self._busy = False

                    self._hold_recording = False

                self._emit_status("Готов · Ctrl+Win")

                return

            max_chunks = int(self.sample_rate / 1024 * self.max_hold_seconds) + 1

            n = 0

            read_err_toasted = False

            while not self._stop_record.is_set() and n < max_chunks:

                try:

                    data = stream.read(1024, exception_on_overflow=False)

                except OSError as e:

                    log.exception("Ошибка чтения микрофона")

                    if not read_err_toasted:

                        read_err_toasted = True

                        with self._lock:

                            show = self._mic_fail_toast_ok

                            if show:

                                self._mic_fail_toast_ok = False

                        if show:

                            self._emit_toast("Микрофон", f"Сбой записи: {e}", True)

                    break

                with self._chunk_lock:

                    self._audio_chunks.append(data)

                n += 1

        finally:

            if stream is not None:

                try:

                    stream.stop_stream()

                    stream.close()

                except Exception:

                    pass

            try:

                p.terminate()

            except Exception:

                pass



    def _start_hold_recording(self) -> None:

        with self._lock:

            # Если уже идёт запись, не начинаем новую
            if self._hold_recording:

                return

            # Если обрабатывается предыдущая запись — НЕ начинаем новую (чтобы не зависало)
            if self._busy:

                print("[Whisper] Обработка предыдущей записи ещё идёт, пропуск новой записи.", flush=True)

                self._emit_status("Подожди, идёт распознавание…")

                return

            self._hold_recording = True

            self._busy = True

            self._cancel_processing.clear()  # сбрасываем флаг отмены для новой записи

        self._stop_record.clear()

        with self._chunk_lock:

            self._audio_chunks.clear()

        _play_record_start_sound()

        print("[Запись] Зажато Ctrl+Win — говори…", flush=True)

        self._emit_status("Запись… (отпусти Ctrl+Win)")

        self._record_thread = threading.Thread(target=self._record_worker, daemon=True)

        self._record_thread.start()



    def _stop_hold_recording_and_process(self) -> None:

        with self._lock:

            if not self._hold_recording:

                return

            self._hold_recording = False

        self._stop_record.set()

        if self._record_thread is not None:

            self._record_thread.join(timeout=5.0)

            self._record_thread = None

        with self._chunk_lock:

            chunks = self._audio_chunks[:]

            self._audio_chunks.clear()

        if not chunks:

            print("[Whisper] Нет аудио (слишком коротко?).", flush=True)

            with self._lock:

                self._busy = False

            self._emit_status("Готов · Ctrl+Win")

            return

        raw = b"".join(chunks)

        audio = np.frombuffer(raw, dtype=np.float32)

        min_samples = int(0.25 * self.sample_rate)

        if audio.size < min_samples:

            print("[Whisper] Запись слишком короткая, пропуск.", flush=True)

            with self._lock:

                self._busy = False

            self._emit_status("Готов · Ctrl+Win")

            return

        # Предупреждение при очень длинных записях (>30 сек)

        duration_sec = audio.size / self.sample_rate

        if duration_sec > 30:

            print(f"[Whisper] Длинная запись ({duration_sec:.1f} сек), обработка может занять время…", flush=True)



        def work() -> None:

            try:

                want_spk = self._speaker_verify or os.environ.get(

                    "WHISPER_SPEAKER_VERIFY", ""

                ).strip().lower() in ("1", "true", "yes")

                verify_tmp: str | None = None

                try:

                    if want_spk:

                        try:

                            from speaker_verify import (

                                SpeakerRejected,

                                SpeakerVerifyUnavailable,

                                embedding_path,

                                verify_wav_file_or_raise,

                            )

                            if embedding_path().is_file():

                                import soundfile as sf

                                with tempfile.NamedTemporaryFile(

                                    suffix=".wav", delete=False

                                ) as tmp:

                                    verify_tmp = tmp.name

                                sf.write(verify_tmp, audio, self.sample_rate)

                                try:

                                    verify_wav_file_or_raise(

                                        verify_tmp,

                                        thr_override=self._speaker_threshold,

                                    )

                                except SpeakerVerifyUnavailable:

                                    pass

                                except SpeakerRejected as e:

                                    log.info("Голос не совпал с эталоном: %s", e)

                                    self._emit_toast("Голос", str(e)[:220], True)

                                    return

                        except ImportError:

                            log.warning("speaker_verify недоступен (requirements-speaker.txt)")

                finally:

                    if verify_tmp:

                        try:

                            os.unlink(verify_tmp)

                        except OSError:

                            pass

                print("[Whisper] Обработка…", flush=True)

                self._emit_status("Распознавание…")

                # Транскрипция с таймаутом (large-v3 / холодный GPU легко > 60 с)
                text = None

                tmo = self._transcribe_timeout_sec

                def transcribe_with_timeout() -> str | None:

                    try:

                        return self._transcribe_audio(audio)

                    except Exception as e:

                        print(f"[Ошибка транскрипции] {e}", file=sys.stderr, flush=True)

                        log.exception("Транскрипция")

                        self._emit_toast(

                            "Распознавание",

                            f"Ошибка: {type(e).__name__}: {str(e)[:160]}",

                            True,

                        )

                        return None

                # Запускаем транскрипцию в отдельном потоке с таймаутом

                result_container: list[str | None] = []

                def run_transcribe() -> None:

                    if self._cancel_processing.is_set():

                        return

                    result_container.append(transcribe_with_timeout())

                transcribe_thread = threading.Thread(target=run_transcribe, daemon=True)

                transcribe_thread.start()

                transcribe_thread.join(timeout=tmo)

                if transcribe_thread.is_alive():

                    print(f"[Whisper] Таймаут транскрипции ({tmo:.0f} с), отмена.", flush=True)

                    log.warning("Таймаут транскрипции %.0f с", tmo)

                    self._emit_toast(

                        "Таймаут",

                        f"Распознавание дольше {tmo:.0f} с — отменено. Увеличь WHISPER_HOTKEY_TRANSCRIBE_TIMEOUT или уменьши модель.",

                        True,

                    )

                    self._cancel_processing.set()

                    text = None

                elif result_container:

                    text = result_container[0]

                # Проверяем отмену перед дальнейшей обработкой

                if self._cancel_processing.is_set():

                    print("[Whisper] Обработка отменена (начата новая запись).", flush=True)

                    return

                if text:

                    if self.spoken_punctuation:

                        text = apply_spoken_punctuation(text)

                    if text and not self._cancel_processing.is_set():

                        self._insert_text(text)

                        preview = (text[:220] + "…") if len(text) > 220 else text

                        self._emit_toast("Готово", preview, False)

                elif not self._cancel_processing.is_set():

                    print("[Whisper] Текст не распознан.", flush=True)

                    log.info("Пустой результат распознавания")

                    self._emit_toast("Нет текста", "Речь не распознана или слишком тихо.", False)

            except Exception as e:

                if not self._cancel_processing.is_set():

                    print(f"[Ошибка] {e}", file=sys.stderr, flush=True)

                    log.exception("Обработка записи")

                    self._emit_toast("Ошибка", str(e)[:200], True)

                    import traceback

                    traceback.print_exc()

            finally:

                with self._lock:

                    self._busy = False

                self._emit_status("Готов · Ctrl+Win")



        threading.Thread(target=work, daemon=True).start()



    def _on_global_key(self, event: object) -> None:

        try:

            active = self._combo_pressed()

        except Exception:

            return

        if not active:

            with self._lock:

                self._mic_fail_toast_ok = True

        if active and not self._last_combo:

            self._start_hold_recording()

        elif not active and self._last_combo:

            self._stop_hold_recording_and_process()

        self._last_combo = active



    def _transcribe_audio(self, audio: np.ndarray) -> str:

        self._load_model()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:

            import soundfile as sf



            tmp_path = tmp.name

            sf.write(tmp_path, audio, self.sample_rate)

            try:

                segments, info = self.model.transcribe(

                    tmp_path,

                    language=self.language,

                    beam_size=5,

                )

                # Собираем ВСЕ сегменты (генератор нужно полностью прочитать)
                text_parts = []
                for seg in segments:
                    text = seg.text.strip()
                    if text:
                        text_parts.append(text)

                result = " ".join(text_parts).strip()
                result = _filter_hallucinations(result)

                if info.language:

                    print(f"[Whisper] Язык: {info.language}", flush=True)

                # Логируем полный текст для отладки
                if result:
                    print(f"[Whisper] Полный текст ({len(result)} символов): {result[:100]}...", flush=True)

                return result

            finally:

                try:

                    os.unlink(tmp_path)

                except Exception:

                    pass



    def _insert_text(self, text: str) -> None:

        if not text:

            print("[Whisper] Пустой текст, пропуск.", flush=True)

            return

        with self._insert_lock:

            print(f"[Whisper] Вставляю текст ({len(text)} символов): {text}", flush=True)

            pyperclip.copy(text)

            time.sleep(0.25)  # буфер обмена должен успеть обновиться

            try:

                for mod in ("ctrl", "left windows", "right windows", "windows", "shift", "alt"):
                    try:
                        keyboard.release(mod)
                    except Exception:
                        pass

                time.sleep(0.12)

                if sys.platform == "win32":
                    _win32_paste_once()
                else:
                    keyboard.press_and_release("ctrl+v")

                time.sleep(0.05)

                print("[Whisper] Текст вставлен.", flush=True)

            except Exception:
                print("[Whisper] Вставка не удалась, текст в буфере обмена.", flush=True)
                print("[Whisper] Нажми Ctrl+V вручную.", flush=True)
                log.warning("Вставка через Ctrl+V не удалась")
                self._emit_toast("Вставка текста", "Ctrl+V не сработал — вставь вручную из буфера.", True)



    def run(self) -> None:

        print("[Whisper] Зажми Ctrl+Win — запись (звук), отпусти — распознавание.", flush=True)

        print(f"[Whisper] Макс. длительность удержания: {self.max_hold_seconds:.0f} с. Выход: Ctrl+C", flush=True)

        self._emit_status("Подключаю клавиши…")

        try:

            keyboard.hook(self._on_global_key)

        except Exception as e:

            print(f"\n[ОШИБКА] Не удалось подключить перехват клавиш: {e}", file=sys.stderr, flush=True)

            if sys.platform == "win32":

                print("[ОШИБКА] На Windows обычно нужен запуск от имени администратора.", file=sys.stderr, flush=True)

            self._emit_status("Ошибка: нет перехвата клавиш (нужен админ?)")

            log.exception("Перехват клавиш")

            self._emit_toast("Клавиши", "Нет перехвата Ctrl+Win — запусти от имени администратора.", True)

            raise

        self._emit_status("Готов · Ctrl+Win")

        try:

            keyboard.wait()

        except KeyboardInterrupt:

            print("\n[Whisper] Остановка…", flush=True)





def main() -> int:

    import argparse

    from whisper_file_log import configure
    from whisper_models import resolve_model

    configure("whisper.hotkey", "whisper_hotkey.log")



    _def_model = os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"

    p = argparse.ArgumentParser(description="Whisper: запись пока зажаты Ctrl+Win")

    p.add_argument(
        "--model",
        default=_def_model,
        help="Модель или ключ пресета (large-v3, ru-ct2-pav88, …)",
    )

    p.add_argument("--device", default="cuda", help="cuda | cpu")

    p.add_argument("--compute-type", default="int8", help="int8, float16, …")

    p.add_argument("--language", default=None, help="ru, en или авто")

    p.add_argument(

        "--max-hold",

        type=float,

        default=120.0,

        help="Максимум секунд удержания (защита от переполнения памяти)",

    )

    p.add_argument(

        "--no-spoken-punctuation",

        action="store_true",

        help="Не заменять «запятая», «точка» и т.д. на знаки",

    )

    p.add_argument(

        "--speaker-verify",

        action="store_true",

        help="Сверять с эталоном ~/.whisper/speaker_embedding.npy (см. requirements-speaker.txt)",

    )

    p.add_argument(

        "--speaker-threshold",

        type=float,

        default=None,

        help="Порог сходства голоса (иначе WHISPER_SPEAKER_THRESHOLD или значение по умолчанию)",

    )

    args = p.parse_args()



    if sys.platform == "win32":

        try:

            import ctypes



            if ctypes.windll.shell32.IsUserAnAdmin() == 0:

                print(

                    "ВНИМАНИЕ: без прав администратора глобальный перехват клавиш может не работать.",

                    file=sys.stderr,

                )

        except Exception:

            pass



    sthr = args.speaker_threshold

    if sthr is None and (os.environ.get("WHISPER_SPEAKER_THRESHOLD") or "").strip():

        try:

            sthr = float(os.environ["WHISPER_SPEAKER_THRESHOLD"].strip())

        except ValueError:

            sthr = None

    spk = args.speaker_verify or (

        os.environ.get("WHISPER_SPEAKER_VERIFY", "").strip().lower() in ("1", "true", "yes")

    )

    service = WhisperHotkey(

        model=resolve_model(args.model),

        device=args.device,

        compute_type=args.compute_type,

        language=args.language,

        max_hold_seconds=args.max_hold,

        spoken_punctuation=not args.no_spoken_punctuation,

        speaker_verify=spk,

        speaker_threshold=sthr,

    )

    try:

        service.run()

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


