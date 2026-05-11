"""
Прокси Groq Speech-to-Text для клиентов из регионов без прямого доступа к api.groq.com.
Деплой: Railway (или любой хост с выходом в Groq). Клиент шлёт сюда тот же multipart, что и в OpenAI API.

Переменные окружения:
  GROQ_API_KEY — ключ на стороне прокси (если клиент не передаёт Authorization).
  PROXY_SHARED_SECRET — опционально; клиент шлёт заголовок X-Whisper-Groq-Proxy-Secret.

Запуск: uvicorn main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os

import requests
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

GROQ_TRANSCRIPTIONS = "https://api.groq.com/openai/v1/audio/transcriptions"
SERVER_KEY = (os.environ.get("GROQ_API_KEY") or os.environ.get("WHISPER_GROQ_API_KEY") or "").strip()
SHARED = (os.environ.get("PROXY_SHARED_SECRET") or "").strip()

app = FastAPI(title="Whisper Groq proxy", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health() -> dict[str, str | bool]:
    return {"ok": True, "service": "whisper-groq-proxy", "groq_key_configured": bool(SERVER_KEY)}


@app.post("/openai/v1/audio/transcriptions")
def transcribe(
    file: UploadFile = File(..., description="WAV и т.д., как у Groq"),
    model: str = Form(...),
    response_format: str = Form(default="json"),
    language: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
    x_whisper_groq_proxy_secret: str | None = Header(default=None, alias="X-Whisper-Groq-Proxy-Secret"),
) -> Response:
    if SHARED and (x_whisper_groq_proxy_secret or "").strip() != SHARED:
        raise HTTPException(status_code=401, detail="Invalid or missing proxy secret")

    auth = (authorization or "").strip()
    if not auth.lower().startswith("bearer "):
        if not SERVER_KEY:
            raise HTTPException(
                status_code=401,
                detail="Proxy: set GROQ_API_KEY or send Authorization: Bearer from client",
            )
        auth = f"Bearer {SERVER_KEY}"
    else:
        pass  # клиентский ключ → в Groq как есть

    raw = file.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    fn = file.filename or "audio.wav"
    ct = file.content_type or "audio/wav"
    files = {"file": (fn, raw, ct)}
    data: list[tuple[str, str]] = [("model", model), ("response_format", response_format)]
    if language:
        data.append(("language", language))

    try:
        r = requests.post(
            GROQ_TRANSCRIPTIONS,
            headers={
                "Authorization": auth,
                "Accept": "application/json",
                "User-Agent": "WhisperGroqProxy/1.0",
            },
            files=files,
            data=dict(data),
            timeout=(60.0, 600.0),
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Groq upstream: {e}") from e

    ct_out = r.headers.get("content-type", "application/json")
    return Response(content=r.content, status_code=r.status_code, media_type=ct_out)
