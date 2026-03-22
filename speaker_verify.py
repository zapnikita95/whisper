"""
Верификация говорящего по embedding (Resemblyzer). Опциональные зависимости: requirements-speaker.txt
Эталон: ~/.whisper/speaker_embedding.npy (или WHISPER_SPEAKER_EMBEDDING_PATH).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

DEFAULT_THRESHOLD = 0.72


class SpeakerRejected(Exception):
    """Сходство с эталоном ниже порога."""


class SpeakerVerifyUnavailable(Exception):
    """Нет библиотеки или эталона."""


def embedding_path() -> Path:
    raw = (os.environ.get("WHISPER_SPEAKER_EMBEDDING_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".whisper" / "speaker_embedding.npy"


def threshold() -> float:
    try:
        return float(os.environ.get("WHISPER_SPEAKER_THRESHOLD", str(DEFAULT_THRESHOLD)))
    except ValueError:
        return DEFAULT_THRESHOLD


def _install_webrtcvad_stub_if_needed() -> None:
    """
    webrtcvad на Windows часто требует MSVC для сборки. Резерв: заглушка — весь сигнал «с речью»,
    trim_long_silences по сути не режет (качество VAD хуже, но embedding и проверка работают).
    """
    import sys
    import types

    if "webrtcvad" in sys.modules:
        return
    try:
        import webrtcvad  # noqa: F401
    except ImportError:
        pass
    else:
        return
    m = types.ModuleType("webrtcvad")

    class Vad:
        __slots__ = ()

        def __init__(self, mode: int = 3) -> None:
            pass

        def is_speech(self, pcm: bytes, sample_rate: int = 16000) -> bool:
            return True

    m.Vad = Vad
    sys.modules["webrtcvad"] = m


def _load_encoder():
    _install_webrtcvad_stub_if_needed()
    try:
        import torch
        from resemblyzer import VoiceEncoder, preprocess_wav
    except ImportError as e:
        raise SpeakerVerifyUnavailable(
            "Установи зависимости: pip install -r requirements-speaker.txt"
        ) from e
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return VoiceEncoder(device=dev), preprocess_wav


def enroll_from_wav(wav_path: str | Path) -> None:
    """Строит embedding из WAV и сохраняет в embedding_path()."""
    path = Path(wav_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    encoder, preprocess_wav = _load_encoder()
    wav = preprocess_wav(path)
    if wav.size < 8000:
        raise ValueError("Слишком короткий файл для эталона (нужно хотя бы ~0.5 с аудио).")
    emb = encoder.embed_utterance(wav)
    out = embedding_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    np.save(out, emb.astype(np.float32))
    return None


def load_reference() -> np.ndarray | None:
    p = embedding_path()
    if not p.is_file():
        return None
    ref = np.load(p)
    return np.asarray(ref, dtype=np.float32).flatten()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def score_wav_file(wav_path: str | Path) -> float:
    """Косинусное сходство с эталоном [0..1] для целого utterance."""
    ref = load_reference()
    if ref is None:
        raise SpeakerVerifyUnavailable(
            "Нет эталона — Mac: --enroll-speaker или меню трея; Windows hotkey: «Записать эталон голоса»."
        )
    encoder, preprocess_wav = _load_encoder()
    wav = preprocess_wav(Path(wav_path))
    if wav.size < 4000:
        return 0.0
    emb = encoder.embed_utterance(wav)
    return cosine_similarity(ref, emb)


def verify_wav_file_or_raise(wav_path: str | Path, *, thr_override: float | None = None) -> None:
    """403-уровень: SpeakerRejected если сходство ниже порога."""
    thr = thr_override if thr_override is not None else threshold()
    sim = score_wav_file(wav_path)
    if sim < thr:
        raise SpeakerRejected(
            f"Голос не совпадает с эталоном (сходство {sim:.2f}, нужно ≥ {thr:.2f})."
        )


def should_verify_server() -> bool:
    return os.environ.get("WHISPER_SPEAKER_VERIFY", "").strip().lower() in ("1", "true", "yes")


def verify_if_enabled_server(wav_path: str | Path) -> None:
    """Вызывать из transcribe: при включённом verify и наличии эталона — проверить."""
    import logging

    _log = logging.getLogger(__name__)

    if not should_verify_server():
        return
    ref = load_reference()
    if ref is None:
        return
    try:
        verify_wav_file_or_raise(wav_path, thr_override=None)
    except SpeakerRejected:
        raise
    except SpeakerVerifyUnavailable:
        return
    except Exception:
        # Реземблер/torch/CUDA не должны ронять транскрипцию целиком — только лог.
        _log.exception(
            "speaker_verify: внутренняя ошибка, проверка пропущена для этого запроса"
        )
        return
