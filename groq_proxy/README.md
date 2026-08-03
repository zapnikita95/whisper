# Groq proxy (Railway + Layero RF)

Если с твоей сети **api.groq.com** / `*.up.railway.app` не открывается (РФ без VPN):

1. Origin остаётся на Railway: `https://whisper-groq-proxy-production.up.railway.app`
2. Публичное зеркало для РФ — **Layero**: `https://whisper-groq-proxy.layero.app` (см. `rf-mirror-layero/`)

```env
WHISPER_GROQ_PROXY_URL=https://whisper-groq-proxy.layero.app
```

Mac-клиент (b53+) использует Layero URL по умолчанию, прокси включён.

## Railway origin

Проект: `whisper-groq-proxy` (`railway up` из `groq_proxy/`).

| Переменная | Значение |
|------------|----------|
| `GROQ_API_KEY` | ключ `gsk_…` |
| `PROXY_SHARED_SECRET` | опционально |

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Клиент: `POST {PROXY}/openai/v1/audio/transcriptions` (тот же multipart, что у Groq).
