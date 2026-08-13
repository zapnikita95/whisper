"""

Глобальная комбинация: зажми Ctrl+Win — идёт запись, отпусти — распознавание и вставка текста.

Звук при начале записи. Слова «запятая», «точка» и т.д. превращаются в знаки препинания.

"""

from __future__ import annotations



import ctypes

import os

import re

import sys

import tempfile

import concurrent.futures

import logging

import threading

import time

from pathlib import Path

from collections.abc import Callable
from typing import Any

from whisper_win_cuda_path import prepend_nvidia_cuda_bins_to_path
from whisper_text_post import apply_spoken_punctuation, finalize_transcript
from whisper_vocab import (
    apply_replacements as vocab_apply_replacements,
    build_initial_prompt as vocab_build_initial_prompt,
)


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

    from whisper_nvidia_path import prepend_nvidia_cuda_bin_dirs_to_path

    _n, cublas_ok = prepend_nvidia_cuda_bin_dirs_to_path()

    return cublas_ok


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






# apply_spoken_punctuation: re-exported from whisper_text_post

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


def _collapse_exact_duplicate(text: str) -> str:
    """Whisper и двойной paste иногда дают один и тот же абзац два раза подряд."""
    t = text.strip()
    if len(t) < 2:
        return t
    n = len(t)
    if n % 2 == 0 and t[: n // 2] == t[n // 2 :]:
        return t[: n // 2].strip()
    # Повтор блока без пробела между копиями: «…подставляются.Так, это…»
    half = n // 2
    for shift in range(-3, 4):
        cut = half + shift
        if cut <= 0 or cut >= n:
            continue
        if t[:cut] == t[cut:]:
            return t[:cut].strip()
    return t


def _join_segment_texts(segments) -> str:
    parts: list[str] = []
    for seg in segments:
        piece = seg.text.strip()
        if not piece:
            continue
        if parts and piece == parts[-1]:
            continue
        parts.append(piece)
    joined = " ".join(parts).strip()
    return _collapse_exact_duplicate(_filter_hallucinations(joined))


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

        compute_type: str = "int8_float16",

        language: str | None = None,

        sample_rate: int = 16000,

        channels: int = 1,

        max_hold_seconds: float = 120.0,

        spoken_punctuation: bool = True,

        status_callback: Callable[[str], None] | None = None,

        toast_callback: Callable[[str, str, bool], None] | None = None,

        speaker_verify: bool = False,

        speaker_threshold: float | None = None,

        paste_mode: str = "auto",

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

        self._last_insert_text = ""

        self._last_insert_mono = 0.0

        self._mic_fail_toast_ok = True

        self._speaker_verify = speaker_verify

        self._speaker_threshold = speaker_threshold

        self._paste_mode = paste_mode if paste_mode in ("auto", "clipboard", "history_only") else "auto"

        self._transcribe_timeout_sec = _transcribe_timeout_sec_default()

        self._gpu_pool: concurrent.futures.ThreadPoolExecutor | None = None



    def _gpu_pool_get(self) -> concurrent.futures.ThreadPoolExecutor:

        if self._gpu_pool is None:

            self._gpu_pool = concurrent.futures.ThreadPoolExecutor(

                max_workers=1,

                thread_name_prefix="whisper-gpu",

            )

        return self._gpu_pool



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



    def _load_model_impl(self) -> None:

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

        from whisper_quality import load_whisper_model, resolve_quality_compute_type

        self.compute_type = resolve_quality_compute_type(
            device=self.device, explicit=self.compute_type
        )



        print(f"[Whisper] Загрузка модели {self.model_name}...", flush=True)

        log.info("Загрузка модели %s (%s, %s)", self.model_name, self.device, self.compute_type)

        try:

            self.model, self.compute_type = load_whisper_model(

                self.model_name,

                device=self.device,

                compute_type=self.compute_type,

                log_warning=log.warning,

            )

        except OSError as e:

            log.exception("Модель: OSError")

            self._emit_toast(

                "Сеть или диск",

                "Не удалось загрузить модель для Ctrl+Win (локально в Hotkey, не HTTP-сервер): сеть, Hugging Face или диск.",

                True,

            )

            raise

        except Exception as e:

            log.exception("Модель: ошибка")

            self._emit_toast(

                "Модель",

                f"Hotkey (локально): не загрузить веса — {type(e).__name__}. Сервер для Mac — отдельное окно Whisper GPU Server.",

                True,

            )

            raise

        print("[Whisper] Модель загружена.", flush=True)

        log.info("Модель загружена compute_type=%s", self.compute_type)



    def _gpu_transcribe_job(self, audio: np.ndarray) -> str | None:

        """Всегда выполняется в одном GPU-потоке (CUDA/CT2 иначе на Windows зависают)."""

        if self._cancel_processing.is_set():

            return None

        try:

            self._load_model_impl()

            return self._transcribe_audio(audio)

        except Exception as e:

            print(f"[Ошибка транскрипции] {e}", file=sys.stderr, flush=True)

            log.exception("Транскрипция (GPU-поток)")

            self._emit_toast(

                "Распознавание",

                f"Ошибка: {type(e).__name__}: {str(e)[:160]}",

                True,

            )

            return None



    def _current_app_name(self) -> str | None:
        """Имя активного приложения (процесс / окно) для vocab + auto AI mode."""
        try:
            from whisper_app_context import frontmost_app

            return frontmost_app()
        except Exception as e:
            log.debug("current_app_name_err: %s", e)
            return None

    def _vocab_prompt_for_current_app(self) -> tuple[str, str | None]:
        try:
            app = self._current_app_name()
            return vocab_build_initial_prompt(app), app
        except Exception as e:
            log.debug("vocab_build_prompt_err: %s", e)
            return "", None

    def _apply_vocab_replacements_local(self, text: str, app_name: str | None) -> str:
        if not text:
            return text
        try:
            replaced = vocab_apply_replacements(text, app_name)
            if replaced != text:
                log.info(
                    "vocab_replacements_applied app=%r before=%d after=%d",
                    app_name,
                    len(text),
                    len(replaced),
                )
            return replaced
        except Exception as e:
            log.debug("vocab_apply_err: %s", e)
            return text

    def _local_gpu_transcribe_for_chain(
        self, audio: np.ndarray, *, initial_prompt: str | None = None
    ) -> str:

        """Локальный Whisper без тостов — для цепочки с Groq."""

        if self._cancel_processing.is_set():

            return ""

        self._load_model_impl()

        return self._transcribe_audio(audio, initial_prompt=initial_prompt) or ""



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

        try:
            from whisper_app_context import frontmost_app, suggest_ai_mode
            from whisper_ai_modes import mode_label, read_hotkey_ai_mode_pref
            from whisper_hud import hud_show

            _app = frontmost_app()
            _pref = read_hotkey_ai_mode_pref()
            _mode = suggest_ai_mode(_app) if _pref == "auto" else _pref
            hud_show(app=_app, mode=mode_label(_mode))
        except Exception:
            log.debug("hud_show failed", exc_info=True)

        print("[Запись] Зажато Ctrl+Win — говори…", flush=True)

        self._emit_status("Запись… (отпусти Ctrl+Win)")

        self._record_thread = threading.Thread(target=self._record_worker, daemon=True)

        self._record_thread.start()



    def _stop_hold_recording_and_process(self) -> None:

        try:
            from whisper_hud import hud_hide
            hud_hide()
        except Exception:
            pass

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

                text = None

                tmo = self._transcribe_timeout_sec

                from whisper_groq import hotkey_transcribe_backend_order

                order = hotkey_transcribe_backend_order(log_info=log.info)

                log.info("transcribe route=%s", order)

                vocab_prompt, vocab_app = self._vocab_prompt_for_current_app()

                for idx, backend in enumerate(order):

                    if self._cancel_processing.is_set():

                        return

                    try:

                        if backend == "server":

                            fut = self._gpu_pool_get().submit(
                                self._local_gpu_transcribe_for_chain,
                                audio,
                                initial_prompt=vocab_prompt or None,
                            )

                            try:

                                raw = fut.result(timeout=tmo)

                            except concurrent.futures.TimeoutError:

                                print(

                                    f"[Whisper] Таймаут GPU ({tmo:.0f} с) — задача ещё в очереди/на видеокарте.",

                                    flush=True,

                                )

                                log.warning(

                                    "Таймаут future.result %.0f с (один GPU-поток)",

                                    tmo,

                                )

                                if idx + 1 < len(order):

                                    continue

                                self._emit_toast(

                                    "Таймаут",

                                    f"GPU не ответил за {tmo:.0f} с (WHISPER_HOTKEY_TRANSCRIBE_TIMEOUT). Это не длина записи; после обновления hotkey короткая речь не должна упираться в минуту.",

                                    True,

                                )

                                self._cancel_processing.set()

                                text = None

                                break

                            text = (raw or "").strip() or None

                        else:

                            from whisper_groq import (

                                CloudQuotaExceeded,

                                groq_http_timeout_tuple,

                                post_groq_audio_transcription,

                                read_hotkey_cloud_token_pref,

                                read_hotkey_groq_api_key_pref,
                                read_hotkey_groq_proxy_enabled_pref,

                                read_hotkey_groq_proxy_secret_pref,

                                read_hotkey_groq_proxy_url_pref,

                            )

                            import soundfile as sf

                            self._emit_status("Распознавание (Groq)…")

                            tmp_groq: str | None = None

                            try:

                                fd, tmp_groq = tempfile.mkstemp(suffix=".wav")

                                os.close(fd)

                                sf.write(tmp_groq, audio, self.sample_rate)

                                conn, read = groq_http_timeout_tuple(read_cap=600.0)

                                out = post_groq_audio_transcription(

                                    tmp_groq,

                                    language=self.language,

                                    timeout=(conn, read),

                                    log_error=log.error,

                                    pref_api_key=read_hotkey_groq_api_key_pref(),

                                    pref_proxy_url=read_hotkey_groq_proxy_url_pref(),

                                    pref_proxy_secret=read_hotkey_groq_proxy_secret_pref(),
                                    pref_proxy_enabled=read_hotkey_groq_proxy_enabled_pref(),

                                    pref_cloud_token=read_hotkey_cloud_token_pref(),

                                    prompt=vocab_prompt or None,

                                )

                                text = (out.get("text") or "").strip() or None

                            finally:

                                if tmp_groq:

                                    try:

                                        os.unlink(tmp_groq)

                                    except OSError:

                                        pass

                        if text:

                            break

                        if idx + 1 < len(order):

                            log.info("transcribe_empty backend=%s try_fallback", backend)

                            continue

                    except Exception as e:

                        print(f"[Ошибка распознавания] {e}", file=sys.stderr, flush=True)

                        log.exception("transcribe backend=%s", backend)

                        if idx + 1 < len(order):

                            continue

                        self._emit_toast("Распознавание", str(e)[:200], True)

                        text = None

                        break

                # Проверяем отмену перед дальнейшей обработкой

                if self._cancel_processing.is_set():

                    print("[Whisper] Обработка отменена (начата новая запись).", flush=True)

                    return

                if text:

                    text = finalize_transcript(
                        text,
                        spoken_punctuation=self.spoken_punctuation,
                        app_name=vocab_app,
                    )
                    if text:
                        try:
                            from whisper_ai_modes import (
                                AiModeProRequired,
                                apply_ai_mode,
                                clamp_mode_for_plan,
                                mode_label,
                                read_hotkey_ai_mode_pref,
                                resolve_cloud_plan_for_gate,
                                resolve_effective_mode,
                            )
                            from whisper_groq import (
                                groq_api_key_from_env,
                                read_hotkey_cloud_token_pref,
                                read_hotkey_groq_api_key_pref,
                                read_hotkey_groq_proxy_enabled_pref,
                                read_hotkey_groq_proxy_secret_pref,
                                read_hotkey_groq_proxy_url_pref,
                            )
                            has_byok = bool(
                                groq_api_key_from_env() or read_hotkey_groq_api_key_pref()
                            )
                            local_stt_ok = backend == "server"
                            plan = (
                                None
                                if (has_byok or local_stt_ok)
                                else resolve_cloud_plan_for_gate(
                                    pref_cloud_token=read_hotkey_cloud_token_pref(),
                                    pref_proxy_url=read_hotkey_groq_proxy_url_pref(),
                                )
                            )
                            allow_auto = bool(has_byok or local_stt_ok or (plan or "") == "pro")
                            text, mode = resolve_effective_mode(
                                text,
                                app_name=vocab_app,
                                pref_mode=read_hotkey_ai_mode_pref(),
                                allow_auto_context=allow_auto,
                                free_fallback="polish" if allow_auto else "raw",
                            )
                            # Free Cloud: clamp email/chat/code down to polish/raw
                            mode = clamp_mode_for_plan(
                                mode, plan, has_byok=has_byok, local_stt_ok=local_stt_ok
                            )
                            if mode != "raw":
                                from whisper_quality import ai_rewrite_available

                                if not ai_rewrite_available():
                                    log.info("ai_mode_skip mode=%s groq_unconfigured", mode)
                                else:
                                    self._emit_status(f"AI Mode: {mode_label(mode)}…")
                                    text = apply_ai_mode(
                                        text,
                                        mode,
                                        cloud_plan=plan,
                                        has_byok=has_byok,
                                        local_stt_ok=local_stt_ok,
                                        pref_api_key=read_hotkey_groq_api_key_pref(),
                                        pref_proxy_url=read_hotkey_groq_proxy_url_pref(),
                                        pref_proxy_secret=read_hotkey_groq_proxy_secret_pref(),
                                        pref_proxy_enabled=read_hotkey_groq_proxy_enabled_pref(),
                                        pref_cloud_token=read_hotkey_cloud_token_pref(),
                                        log_error=log.error,
                                    )
                        except AiModeProRequired as e:
                            log.warning("ai_mode_pro_required: %s", e)
                            self._emit_toast("Whisper Cloud Pro", str(e)[:200], True)
                        except Exception as e:
                            log.exception("ai_mode_failed")
                            self._emit_toast("AI Mode", str(e)[:180], True)

                    if text and not self._cancel_processing.is_set():

                        orig_len = len(text)

                        text = _collapse_exact_duplicate(text.strip())

                        if len(text) != orig_len:

                            log.info("transcribe_deduped chars %d -> %d", orig_len, len(text))

                        log.info("transcribe_ok chars=%d preview=%r", len(text), text[:120])

                        self._insert_text(text)
                        try:
                            from whisper_learn import schedule_learn_from_clipboard, suggest_add_vocab
                            from whisper_groq import (
                                groq_api_key_from_env,
                                read_hotkey_cloud_token_pref,
                                read_hotkey_groq_api_key_pref,
                                read_hotkey_groq_proxy_url_pref,
                            )
                            from whisper_ai_modes import resolve_cloud_plan_for_gate

                            _byok = bool(groq_api_key_from_env() or read_hotkey_groq_api_key_pref())
                            _local = backend == "server"
                            _plan = (
                                None
                                if (_byok or _local)
                                else resolve_cloud_plan_for_gate(
                                    pref_cloud_token=read_hotkey_cloud_token_pref(),
                                    pref_proxy_url=read_hotkey_groq_proxy_url_pref(),
                                )
                            )
                            _learn_ok = bool(_byok or _local or (_plan or "") == "pro")

                            def _on_sug(frm: str, to: str) -> None:
                                self._emit_toast(
                                    "Словарь",
                                    suggest_add_vocab(frm, to, auto_add=True),
                                    False,
                                )

                            schedule_learn_from_clipboard(
                                text,
                                allowed=_learn_ok,
                                on_suggest=_on_sug,
                            )
                        except Exception:
                            log.debug("learn schedule failed", exc_info=True)

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



    def _transcribe_audio(
        self, audio: np.ndarray, *, initial_prompt: str | None = None
    ) -> str:

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:

            import soundfile as sf



            tmp_path = tmp.name

            sf.write(tmp_path, audio, self.sample_rate)

            try:
                from whisper_quality import local_transcribe_kwargs

                _kwargs = local_transcribe_kwargs(
                    language=self.language,
                    initial_prompt=initial_prompt,
                )
                segments, info = self.model.transcribe(tmp_path, **_kwargs)

                result = _join_segment_texts(segments)

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

            print("[Whisper] Empty text, skipping.", flush=True)

            return

        text = _collapse_exact_duplicate(text.strip())

        try:
            from whisper_hotkey_history import append_history

            append_history(text)
        except Exception:
            log.debug("history append failed", exc_info=True)

        mode = self._paste_mode
        if mode == "history_only":
            print("[Whisper] paste_mode=history_only — saved to history only.", flush=True)
            log.info("paste_mode=history_only chars=%d", len(text))
            return

        now = time.monotonic()

        if text == self._last_insert_text and now - self._last_insert_mono < 5.0:

            log.warning(

                "insert_skipped duplicate paste (%.1f s since last)",

                now - self._last_insert_mono,

            )

            return

        with self._insert_lock:

            print(f"[Whisper] Output text ({len(text)} chars): {text}", flush=True)

            log.info("insert_text chars=%d mode=%s", len(text), mode)

            pyperclip.copy(text)

            if mode == "clipboard":
                print("[Whisper] paste_mode=clipboard — copied to clipboard only.", flush=True)
                self._last_insert_text = text
                self._last_insert_mono = time.monotonic()
                return

            time.sleep(0.25)

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

                print("[Whisper] Text pasted.", flush=True)

                self._last_insert_text = text

                self._last_insert_mono = time.monotonic()

            except Exception:
                print("[Whisper] Paste failed — text is in the clipboard.", flush=True)
                log.warning("Ctrl+V paste failed")
                self._emit_toast("Paste text", "Ctrl+V failed — paste manually from clipboard.", True)



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

        self._gpu_pool_get().submit(self._load_model_impl)

        try:

            keyboard.wait()

        except KeyboardInterrupt:

            print("\n[Whisper] Остановка…", flush=True)





def main() -> int:

    import argparse

    from whisper_file_log import configure
    from whisper_models import resolve_model

    configure("whisper.hotkey", "whisper_hotkey.log")



    if sys.platform == "win32":

        try:

            from whisper_groq import load_whisper_dotenv_files

            load_whisper_dotenv_files()

        except ImportError:

            pass



    _def_model = os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"

    p = argparse.ArgumentParser(description="Whisper: запись пока зажаты Ctrl+Win")

    p.add_argument(
        "--model",
        default=_def_model,
        help="Модель или ключ пресета (large-v3, ru-ct2-pav88, …)",
    )

    p.add_argument("--device", default="cuda", help="cuda | cpu")

    p.add_argument("--compute-type", default="auto", help="auto | int8_float16 | float16 | int8")

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


