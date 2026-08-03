<<<<<<< HEAD
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
=======
# Groq proxy + Whisper Cloud

Прокси к Groq STT + freemium Cloud (токены `wsk_…`, минуты, Stripe).

Публичный URL (пример): **https://whisper-groq-proxy-production.up.railway.app**

## Эндпоинты

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/` | Health + `stripe_configured` |
| POST | `/v1/devices/register` | `{ "device_id": "…" }` → token + quota |
| GET | `/v1/me` | Квота (`X-Whisper-Cloud-Token` или Bearer `wsk_…`) |
| POST | `/v1/checkout` | Stripe Checkout URL |
| POST | `/v1/stripe/webhook` | Stripe webhooks |
| POST | `/v1/admin/grant-pro` | Ручной Pro (`X-Whisper-Cloud-Admin-Secret`) |
| POST | `/openai/v1/chat/completions` | AI Modes (без метринга минут) |
| POST | `/openai/v1/audio/transcriptions` | STT (как Groq) |

## Режимы авторизации на `/transcriptions`

1. **BYOK** — `Authorization: Bearer gsk_…` → в Groq без метринга  
2. **Cloud** — `X-Whisper-Cloud-Token: wsk_…` → серверный `GROQ_API_KEY` + списание секунд  
3. **Ops** — `X-Whisper-Groq-Proxy-Secret` = `PROXY_SHARED_SECRET` → без метринга  

При `remaining_seconds == 0` → **HTTP 402**.

## Env (Railway)

| Переменная | Значение |
|------------|----------|
| `GROQ_API_KEY` | `gsk_…` |
| `PROXY_SHARED_SECRET` | ops-секрет (не для публичного onboarding) |
| `WHISPER_CLOUD_DB_PATH` | путь к SQLite (или volume `/data`) |
| `WHISPER_CLOUD_ADMIN_SECRET` | для `grant_pro` / admin API |
| `WHISPER_CLOUD_FREE_SECONDS` | default `1800` (30 мин) |
| `WHISPER_CLOUD_PRO_SOFT_CAP_SECONDS` | default `120000` (2000 мин) |
| `STRIPE_SECRET_KEY` | Stripe secret |
| `STRIPE_WEBHOOK_SECRET` | webhook signing secret |
| `STRIPE_PRICE_PRO_MONTHLY` | price id `price_…` |
| `WHISPER_CLOUD_PUBLIC_URL` | публичный URL прокси / сайта |

Подключи **Railway Volume** на `/data`, иначе SQLite будет в эфемерном FS.

## Локально
>>>>>>> origin/main

```bash
cd groq_proxy
pip install -r requirements.txt
set WHISPER_CLOUD_DB_PATH=%TEMP%\whisper_cloud.db
set GROQ_API_KEY=gsk_…
uvicorn main:app --reload --port 8088
```

<<<<<<< HEAD
Клиент: `POST {PROXY}/openai/v1/audio/transcriptions` (тот же multipart, что у Groq).
=======
Ручной Pro:

```bash
python grant_pro.py wsk_... --plan pro
# или remote:
python grant_pro.py wsk_... --remote https://….up.railway.app --admin-secret …
```

## Клиенты

В `.env` / prefs:

```env
WHISPER_GROQ_PROXY_URL=https://whisper-groq-proxy-production.up.railway.app
# WHISPER_CLOUD_TOKEN=wsk_…   # обычно создаётся сам при первой диктовке
```

Windows/Mac: меню **Whisper Cloud** — статус минут, токен, Checkout.
>>>>>>> origin/main
