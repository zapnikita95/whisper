"""
HTTP API сервер для транскрипции через Whisper на GPU (Windows).
Принимает аудио (WAV), возвращает текст.
"""
from __future__ import annotations

import os
import site
import sys
import tempfile
from pathlib import Path

try:
    from fastapi import FastAPI, File, UploadFile, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    import numpy as np
    import soundfile as sf
except ImportError as e:
    print(f"Ошибка импорта: {e}", file=sys.stderr)
    print("Установи: pip install fastapi uvicorn python-multipart", file=sys.stderr)
    sys.exit(1)


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


_prepend_nvidia_cublas_to_path()

from faster_whisper import WhisperModel

app = FastAPI(title="Whisper API Server")

# CORS для запросов с Mac
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # в продакшене лучше указать конкретные IP
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальная модель (загружается при старте)
_model: WhisperModel | None = None
_model_name = "large-v3"
_device = "cuda"
_compute_type = "int8"


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(f"[Server] Загрузка модели {_model_name} ({_device}, {_compute_type})...", flush=True)
        _model = WhisperModel(_model_name, device=_device, compute_type=_compute_type)
        print("[Server] Модель загружена.", flush=True)
    return _model


@app.get("/")
def root():
    """Проверка доступности сервера."""
    return {"status": "ok", "model": _model_name, "device": _device, "ready": _model is not None}


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str | None = None,
    spoken_punctuation: bool = True,
):
    """
    Транскрибирует аудио (WAV, 16kHz моно).
    Параметры:
    - audio: файл WAV
    - language: "ru", "en" или None (авто)
    - spoken_punctuation: заменять "запятая" на "," и т.д.
    """
    if not audio.content_type or "audio" not in audio.content_type.lower():
        raise HTTPException(status_code=400, detail="Ожидается аудио файл")

    try:
        # Читаем аудио
        contents = await audio.read()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(contents)

        try:
            # Проверяем формат
            data, sr = sf.read(tmp_path)
            if len(data.shape) > 1:
                data = data[:, 0]  # берём первый канал если стерео

            # Транскрибируем
            model = get_model()
            segments, info = model.transcribe(tmp_path, language=language, beam_size=5)

            # Собираем ВСЕ сегменты (генератор нужно полностью прочитать)
            text_parts = []
            for seg in segments:
                text_seg = seg.text.strip()
                if text_seg:  # пропускаем пустые
                    text_parts.append(text_seg)
            text = " ".join(text_parts).strip()

            # Применяем произносимую пунктуацию
            if spoken_punctuation and text:
                import re

                pairs = [
                    (r"восклицательный\s+знак", "!"),
                    (r"вопросительный\s+знак", "?"),
                    (r"запятая", ","),
                    (r"точка", "."),
                    (r"тире", "—"),
                ]
                for pattern, repl in pairs:
                    text = re.sub(rf"(?iu)\b(?:{pattern})\b", repl, text)
                text = re.sub(r"\s*,\s*", ", ", text)
                text = re.sub(r"\s*\.\s*", ". ", text)
                text = re.sub(r"\s*!\s*", "! ", text)
                text = re.sub(r"\s*\?\s*", "? ", text)
                text = re.sub(r"\s*—\s*", " — ", text)
                text = re.sub(r"\s{2,}", " ", text).strip()

            return {
                "text": text,
                "language": info.language if info.language else None,
                "language_probability": float(info.language_probability) if hasattr(info, "language_probability") else None,
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки: {str(e)}")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Whisper HTTP API сервер")
    p.add_argument("--host", default="0.0.0.0", help="IP для прослушивания (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="Порт (default: 8000)")
    p.add_argument("--model", default="large-v3", help="Модель Whisper")
    p.add_argument("--device", default="cuda", help="cuda | cpu")
    p.add_argument("--compute-type", default="int8", help="int8, float16, …")
    args = p.parse_args()

    global _model_name, _device, _compute_type
    _model_name = args.model
    _device = args.device
    _compute_type = args.compute_type

    print(f"[Server] Запуск на http://{args.host}:{args.port}", flush=True)
    print(f"[Server] Модель: {_model_name} ({_device}, {_compute_type})", flush=True)
    print("[Server] Для остановки: Ctrl+C", flush=True)

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except KeyboardInterrupt:
        print("\n[Server] Остановка...", flush=True)
        return 0
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
