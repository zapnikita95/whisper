# Groq proxy — Layero RF mirror

Зеркало для РФ без VPN: клиент → Layero → Railway `whisper-groq-proxy` → `api.groq.com`.

## Live URL

```
https://whisper-groq-proxy.layero.app
```

## Deploy

```bash
cd groq_proxy/rf-mirror-layero
npm install
npx layero@latest deploy --json --yes --type next --promote --name whisper-groq-proxy --org zapnikita95
```

Env (опционально): `RAILWAY_ORIGIN=https://whisper-groq-proxy-production.up.railway.app`

## Client

```env
WHISPER_GROQ_PROXY_URL=https://whisper-groq-proxy.layero.app
WHISPER_GROQ_PROXY_ENABLED=1
```

В Mac-клиенте (b53+) прокси Layero включён по умолчанию.
