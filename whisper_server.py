"""
HTTP API сервер для транскрипции через Whisper на GPU (Windows).
Импортируется GUI и uvicorn; точка входа CLI — whisper-server.py (shim) или python -m.
"""
from __future__ import annotations

import os
import site
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    from fastapi import FastAPI, File, Request, UploadFile, HTTPException
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

# Локальная запись на Windows (whisper-hotkey.py) — не HTTP, для подсказок в GUI/API
WINDOWS_LOCAL_HOTKEY_DESC = (
    "whisper-hotkey.py на этом ПК: зажми Ctrl+Win — запись с микрофона, отпусти — распознавание и вставка в активное окно."
)

app = FastAPI(title="Whisper API Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_model: WhisperModel | None = None
_model_name = "large-v3"
_device = "cuda"
_compute_type = "int8"

_clients_lock = threading.Lock()
# ip -> (unix_ts, метка клиента из X-Whisper-Client)
_clients: dict[str, tuple[float, str]] = {}


def touch_client_from_request(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    label = (request.headers.get("x-whisper-client") or "unknown").strip() or "unknown"
    now = time.time()
    with _clients_lock:
        _clients[ip] = (now, label)
        if len(_clients) > 64:
            drop = min(_clients.items(), key=lambda kv: kv[1][0])[0]
            del _clients[drop]


def get_clients_snapshot() -> dict:
    now = time.time()
    with _clients_lock:
        rows = [
            {"ip": ip, "client": lab, "last_seen_ago_sec": round(now - ts, 1)}
            for ip, (ts, lab) in _clients.items()
        ]
    rows.sort(key=lambda r: r["last_seen_ago_sec"])
    return {
        "clients": rows,
        "windows_local_hotkey": WINDOWS_LOCAL_HOTKEY_DESC,
    }


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(f"[Server] Загрузка модели {_model_name} ({_device}, {_compute_type})...", flush=True)
        _model = WhisperModel(_model_name, device=_device, compute_type=_compute_type)
        print("[Server] Модель загружена.", flush=True)
    return _model


@app.get("/")
def root():
    with _clients_lock:
        n = len(_clients)
    return {
        "status": "ok",
        "model": _model_name,
        "device": _device,
        "ready": _model is not None,
        "windows_local_hotkey": WINDOWS_LOCAL_HOTKEY_DESC,
        "recent_http_clients": n,
    }


@app.get("/clients")
def list_clients():
    """Кто недавно вызывал POST /transcribe (по IP и заголовку X-Whisper-Client)."""
    return get_clients_snapshot()


@app.post("/transcribe")
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str | None = None,
    spoken_punctuation: bool = True,
):
    touch_client_from_request(request)

    if not audio.content_type or "audio" not in audio.content_type.lower():
        raise HTTPException(status_code=400, detail="Ожидается аудио файл")

    try:
        contents = await audio.read()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(contents)

        try:
            data, sr = sf.read(tmp_path)
            if len(data.shape) > 1:
                data = data[:, 0]

            model = get_model()
            segments, info = model.transcribe(tmp_path, language=language, beam_size=5)

            text_parts = []
            for seg in segments:
                text_seg = seg.text.strip()
                if text_seg:
                    text_parts.append(text_seg)
            text = " ".join(text_parts).strip()

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
