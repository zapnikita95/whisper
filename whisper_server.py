"""
HTTP API сервер для транскрипции через Whisper на GPU (Windows).
Импортируется GUI и uvicorn; точка входа CLI — whisper-server.py (shim) или python -m.

Важно: лог поднимается ДО импорта faster_whisper — иначе долгая загрузка CUDA/CT2 выглядит как «тишина».
Файлы: whisper_server.log (рядом с exe / WHISPER_LOG_DIR) и %TEMP%\\WhisperServer_last_run.log
"""
from __future__ import annotations

import math
import os
import site
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

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

from whisper_file_log import configure
from whisper_models import resolve_model

_SERVER_TEMP_LOG = "WhisperServer_last_run.log"
log = configure(
    "whisper.server",
    "whisper_server.log",
    flush_each_record=True,
    mirror_temp_basename=_SERVER_TEMP_LOG,
)
log.info(
    "=== старт процесса сервера pid=%s cwd=%s TEMP=%s ===",
    os.getpid(),
    os.getcwd(),
    tempfile.gettempdir(),
)
log.info(
    "Основной лог: рядом с приложением (см. whisper_file_log.log_dir); копия в %%TEMP%%/%s",
    _SERVER_TEMP_LOG,
)


def _prepend_nvidia_cublas_to_path() -> None:
    """
    В venv DLL лежат в site-packages/nvidia/*/bin.
    В PyInstaller onedir — в _MEIPASS (…/_internal), иначе cublas64_12.dll не находится при транскрипции.
    Добавляем все nvidia/*/bin с DLL в начало PATH (cudnn, cufft и т.д.).
    """
    if sys.platform != "win32":
        return
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meip = getattr(sys, "_MEIPASS", None)
        if meip:
            roots.append(Path(meip))
        roots.append(exe_dir / "_internal")
        roots.append(exe_dir)
    try:
        roots.append(Path(site.getusersitepackages()))
    except Exception:
        pass
    try:
        roots.extend(Path(p) for p in site.getsitepackages())
    except Exception:
        pass

    bin_paths: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        nvidia = root / "nvidia"
        if not nvidia.is_dir():
            continue
        try:
            subs = sorted(nvidia.iterdir())
        except OSError:
            continue
        for sub in subs:
            bd = sub / "bin"
            if not bd.is_dir():
                continue
            try:
                if not any(bd.glob("*.dll")):
                    continue
                rs = str(bd.resolve())
            except OSError:
                continue
            if rs in seen:
                continue
            seen.add(rs)
            bin_paths.append(rs)

    if bin_paths:
        os.environ["PATH"] = os.pathsep.join(bin_paths) + os.pathsep + os.environ.get("PATH", "")
        log.info("PATH (nvidia): в начало добавлено %d каталогов …/nvidia/*/bin", len(bin_paths))
    else:
        log.info("PATH (nvidia): каталоги nvidia/*/bin не найдены — возможны ошибки cublas64_12.dll в exe")


_prepend_nvidia_cublas_to_path()

log.info(
    "Импорт faster_whisper (CTranslate2, CUDA DLL и т.д.) — часто 10–90 с, это норма; HTTP ещё не слушает."
)
try:
    from faster_whisper import WhisperModel
except Exception:
    log.exception("Не удалось импортировать faster_whisper")
    raise
log.info("Импорт faster_whisper завершён — дальше создаётся FastAPI/uvicorn.")

try:
    from whisper_version import __version__ as APP_VERSION
except ImportError:
    APP_VERSION = "0.0.0-dev"

# Локальная запись на Windows (whisper-hotkey.py) — не HTTP, для подсказок в GUI/API
WINDOWS_LOCAL_HOTKEY_DESC = (
    "Whisper Hotkey (трей / Ctrl+Win) на этом ПК: запись в микрофон → текст в активное окно. Лог: whisper_hotkey.log."
)

app = FastAPI(title="Whisper API Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_model: Any = None
_model_name = resolve_model(os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3")
_device = (os.environ.get("WHISPER_DEVICE", "cuda").strip() or "cuda")
_compute_type = (os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8")

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


def _safe_language_probability(info: Any) -> float | None:
    lp = getattr(info, "language_probability", None)
    if lp is None:
        return None
    try:
        f = float(lp)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def get_model() -> Any:
    global _model
    if _model is None:
        print(f"[Server] Загрузка модели {_model_name} ({_device}, {_compute_type})...", flush=True)
        log.info("Загрузка модели %s (%s, %s)", _model_name, _device, _compute_type)
        try:
            _model = WhisperModel(_model_name, device=_device, compute_type=_compute_type)
        except OSError:
            log.exception("Модель: OSError (сеть/диск/Hugging Face)")
            raise
        except Exception:
            log.exception("Модель: ошибка загрузки")
            raise
        print("[Server] Модель загружена.", flush=True)
        log.info("Модель загружена")
    return _model


@app.on_event("startup")
def _log_http_ready() -> None:
    log.info(
        "Uvicorn принимает HTTP. GET / отвечает сразу; поле ready=true после первой загрузки весов (POST /transcribe)."
    )


@app.get("/")
def root():
    with _clients_lock:
        n = len(_clients)
    return {
        "status": "ok",
        "app_version": APP_VERSION,
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
            try:
                from speaker_verify import SpeakerRejected, verify_if_enabled_server

                verify_if_enabled_server(tmp_path)
            except ImportError:
                pass
            except SpeakerRejected as e:
                raise HTTPException(status_code=403, detail=str(e)) from e

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
                "language_probability": _safe_language_probability(info),
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except HTTPException:
        raise
    except Exception as e:
        log.exception("POST /transcribe")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки: {str(e)}") from e


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Whisper HTTP API сервер")
    _def_model = os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3"
    _def_dev = os.environ.get("WHISPER_DEVICE", "cuda").strip() or "cuda"
    _def_ct = os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
    p.add_argument("--host", default="0.0.0.0", help="IP для прослушивания (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=8000, help="Порт (default: 8000)")
    p.add_argument(
        "--model",
        default=_def_model,
        help="Модель или ключ пресета (large-v3, ru-ct2-pav88, org/repo на HF)",
    )
    p.add_argument("--device", default=_def_dev, help="cuda | cpu")
    p.add_argument("--compute-type", default=_def_ct, help="int8, float16, …")
    args = p.parse_args()

    global _model_name, _device, _compute_type
    _model_name = resolve_model(args.model)
    _device = args.device
    _compute_type = args.compute_type

    print(f"[Server] Запуск на http://{args.host}:{args.port}", flush=True)
    print(f"[Server] Версия: {APP_VERSION}", flush=True)
    print(f"[Server] Модель: {_model_name} ({_device}, {_compute_type})", flush=True)
    print("[Server] Для остановки: Ctrl+C", flush=True)
    log.info("CLI: uvicorn.run host=%s port=%s", args.host, args.port)

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
