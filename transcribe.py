"""
Транскрипция аудио через faster-whisper.
По умолчанию: large-v3 + int8 — хорошее качество (RU/EN), ~3–4 ГБ VRAM.
"""
from __future__ import annotations

import argparse
import os
import site
import sys
from pathlib import Path


def _prepend_nvidia_cublas_to_path() -> None:
    """На Windows CTranslate2 ищет cublas64_12.dll; wheel nvidia-cublas-cu12 кладёт её в site-packages."""
    if sys.platform != "win32":
        return
    candidates: list[Path] = []
    try:
        candidates.append(Path(site.getusersitepackages()))
    except Exception:
        pass
    try:
        candidates.extend(Path(p) for p in site.getsitepackages())
    except Exception:
        pass
    for base in candidates:
        bin_dir = base / "nvidia" / "cublas" / "bin"
        if (bin_dir / "cublas64_12.dll").is_file():
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            return


def main() -> int:
    p = argparse.ArgumentParser(description="Speech-to-text (faster-whisper)")
    p.add_argument("audio", nargs="?", help="Путь к wav/mp3/flac/m4a и т.д.")
    p.add_argument(
        "--model",
        default="large-v3",
        help="Имя модели: tiny, base, small, medium, large-v2, large-v3 (default)",
    )
    p.add_argument(
        "--device",
        default="cuda",
        help="cuda | cpu (cpu медленнее, зато без VRAM)",
    )
    p.add_argument(
        "--compute-type",
        default="int8",
        help="int8 (мало VRAM), int8_float16, float16, float32",
    )
    p.add_argument("--language", default=None, help="ru, en или авто если не указать")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--vad", action="store_true", help="фильтр тишины (Silero VAD)")
    args = p.parse_args()

    if not args.audio:
        p.print_help()
        return 1

    path = Path(args.audio)
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 1

    _prepend_nvidia_cublas_to_path()

    from faster_whisper import WhisperModel

    print(
        f"Загрузка модели {args.model} ({args.device}, {args.compute_type})...",
        flush=True,
    )
    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
    )

    print(f"Транскрипция: {path}", flush=True)
    segments, info = model.transcribe(
        str(path),
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=args.vad,
    )

    print(f"Язык: {info.language} (confidence {info.language_probability:.2f})", flush=True)
    print("---")
    full = []
    for seg in segments:
        line = f"[{seg.start:.1f}s – {seg.end:.1f}s] {seg.text.strip()}"
        print(line, flush=True)
        full.append(seg.text.strip())
    print("---")
    print("\n".join(full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
