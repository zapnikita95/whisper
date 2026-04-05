# Groq proxy (Railway / VPS)

Если с твоей сети **api.groq.com** не открывается (например, без VPN), подними этот сервис там, где Groq доступен (Railway EU/US и т.д.), и укажи клиентам:

```env
WHISPER_GROQ_PROXY_URL=https://твой-сервис.up.railway.app
# опционально, если задал PROXY_SHARED_SECRET на сервере:
WHISPER_GROQ_PROXY_SECRET=тот_же_секрет
```

На Railway в Variables:

| Переменная | Значение |
|------------|----------|
| `GROQ_API_KEY` | ключ `gsk_…` (прокси сам подставит в Groq, клиенту ключ не нужен) |
| `PROXY_SHARED_SECRET` | длинная случайная строка (рекомендуется) |

Команда старта (Railway сам подставит `PORT`):

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Root directory в Railway: `groq_proxy` (или весь репо + start из этой папки).

Клиент шлёт `POST {WHISPER_GROQ_PROXY_URL}/openai/v1/audio/transcriptions` с тем же телом, что и на Groq. Если на прокси задан только `GROQ_API_KEY`, клиент может **не** хранить ключ Groq локально.

Если клиент передаёт свой `Authorization: Bearer gsk_…`, прокси пробросит его в Groq (ключ на Railway не обязателен, но тогда секрет обязателен, иначе URL увидит кто угодно).
