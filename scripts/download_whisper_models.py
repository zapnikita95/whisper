#!/usr/bin/env python3
"""
Скачать веса всех пресетов из whisper_models.py в кэш Hugging Face.
Запуск: из корня репо, venv с faster-whisper:
  python scripts/download_whisper_models.py
  python scripts/download_whisper_models.py --device cpu --compute-type int8
"""
from __future__ import annotations

import argparse
import os
import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _prepend_nvidia_cublas_to_path() -> None:
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
    p = argparse.ArgumentParser(description="Скачать модели faster-whisper для пресетов проекта")
    p.add_argument("--device", default="cuda", help="cuda | cpu")
    p.add_argument("--compute-type", default="int8", help="int8, float16, …")
    args = p.parse_args()

    _prepend_nvidia_cublas_to_path()

    from faster_whisper import WhisperModel

    from whisper_models import MODEL_PRESETS

    for key, model_id, label in MODEL_PRESETS:
        print(f"[{key}] {model_id} — {label[:60]}…", flush=True)
        try:
            WhisperModel(model_id, device=args.device, compute_type=args.compute_type)
            print(f"  OK: {model_id}", flush=True)
        except Exception as e:
            print(f"  ОШИБКА: {e}", flush=True)
            return 1
    print("Все пресеты загружены в кэш HF.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
