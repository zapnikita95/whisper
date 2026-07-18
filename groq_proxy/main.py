"""
Whisper Groq proxy + Cloud freemium metering.

Env:
  GROQ_API_KEY — server-side Groq key
  PROXY_SHARED_SECRET — ops override (no metering)
  WHISPER_CLOUD_DB_PATH — SQLite path (default: /data/… or local)
  STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET / STRIPE_PRICE_PRO_MONTHLY
  WHISPER_CLOUD_PUBLIC_URL — base URL for redirects
  WHISPER_CLOUD_ADMIN_SECRET — for POST /v1/admin/grant-pro

Run: uvicorn main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

import auth as cloud_auth
import billing
import db
from audio_meta import estimate_audio_seconds

GROQ_TRANSCRIPTIONS = "https://api.groq.com/openai/v1/audio/transcriptions"
SERVER_KEY = (os.environ.get("GROQ_API_KEY") or os.environ.get("WHISPER_GROQ_API_KEY") or "").strip()
ADMIN_SECRET = (os.environ.get("WHISPER_CLOUD_ADMIN_SECRET") or "").strip()

app = FastAPI(title="Whisper Cloud / Groq proxy", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Init immediately (TestClient / some hosts skip startup hooks)
db.init_db()


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "whisper-groq-proxy",
        "cloud": True,
        "groq_key_configured": bool(SERVER_KEY),
        "stripe_configured": billing.stripe_configured(),
        "free_quota_minutes": round(db.FREE_SECONDS_PER_MONTH / 60.0, 1),
    }


class RegisterBody(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=128)


@app.post("/v1/devices/register")
def register_device(body: RegisterBody) -> dict[str, Any]:
    try:
        snap = db.register_device(body.device_id.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return cloud_auth.public_me_payload(snap)


def _require_cloud_token(
    authorization: str | None,
    x_whisper_cloud_token: str | None,
) -> dict[str, Any]:
    bearer = cloud_auth.extract_bearer(authorization)
    token = (x_whisper_cloud_token or "").strip() or (bearer if cloud_auth.is_cloud_token(bearer) else "")
    if not token:
        raise HTTPException(status_code=401, detail="Missing Whisper Cloud token (wsk_…)")
    snap = db.get_by_token(token)
    if not snap:
        raise HTTPException(status_code=401, detail="Invalid cloud token")
    return snap


@app.get("/v1/me")
def me(
    authorization: str | None = Header(default=None),
    x_whisper_cloud_token: str | None = Header(default=None, alias="X-Whisper-Cloud-Token"),
) -> dict[str, Any]:
    return cloud_auth.public_me_payload(_require_cloud_token(authorization, x_whisper_cloud_token))


class CheckoutBody(BaseModel):
    pass


@app.post("/v1/checkout")
def checkout(
    authorization: str | None = Header(default=None),
    x_whisper_cloud_token: str | None = Header(default=None, alias="X-Whisper-Cloud-Token"),
) -> dict[str, Any]:
    snap = _require_cloud_token(authorization, x_whisper_cloud_token)
    if not billing.stripe_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stripe_not_configured",
                "message": "Stripe not configured. Ask the admin for a Pro token or set STRIPE_* env.",
                "remaining_seconds": snap["remaining_seconds"],
            },
        )
    try:
        out = billing.create_checkout_session(
            cloud_token=snap["token"],
            device_id=snap["device_id"],
            customer_id=snap.get("stripe_customer_id"),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}") from e
    return out


class GrantProBody(BaseModel):
    token: str | None = None
    device_id: str | None = None
    plan: str = "pro"


@app.post("/v1/admin/grant-pro")
def admin_grant_pro(
    body: GrantProBody,
    x_whisper_cloud_admin_secret: str | None = Header(
        default=None, alias="X-Whisper-Cloud-Admin-Secret"
    ),
) -> dict[str, Any]:
    if not ADMIN_SECRET or (x_whisper_cloud_admin_secret or "").strip() != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")
    plan = (body.plan or "pro").strip().lower()
    if plan not in ("free", "pro"):
        raise HTTPException(status_code=400, detail="plan must be free or pro")
    snap = None
    if body.token:
        snap = db.set_plan(token=body.token.strip(), plan=plan)
    elif body.device_id:
        snap = db.set_plan(device_id=body.device_id.strip(), plan=plan)
    if not snap:
        raise HTTPException(status_code=404, detail="Device not found")
    return cloud_auth.public_me_payload(snap)


@app.post("/v1/stripe/webhook")
async def stripe_webhook(request: Request) -> dict[str, str]:
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = billing.construct_webhook_event(payload, sig)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}") from e

    # stripe Event object or plain dict
    if hasattr(event, "type"):
        etype = event.type
        data_obj = event.data.object
    else:
        etype = event.get("type")
        data_obj = (event.get("data") or {}).get("object") or {}

    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    if etype == "checkout.session.completed":
        device_id = _get(data_obj, "client_reference_id")
        meta = _get(data_obj, "metadata") or {}
        if not device_id:
            if isinstance(meta, dict):
                device_id = meta.get("device_id")
            else:
                device_id = getattr(meta, "get", lambda *_: None)("device_id") if callable(
                    getattr(meta, "get", None)
                ) else getattr(meta, "device_id", None)
        customer = _get(data_obj, "customer")
        sub = _get(data_obj, "subscription")
        if device_id:
            db.set_plan(
                device_id=str(device_id),
                plan="pro",
                stripe_customer_id=str(customer) if customer else None,
                stripe_subscription_id=str(sub) if sub else None,
            )
    elif etype in (
        "customer.subscription.deleted",
        "customer.subscription.canceled",
    ):
        customer = _get(data_obj, "customer")
        if customer:
            db.set_plan_by_stripe_customer(str(customer), "free")
    elif etype == "customer.subscription.updated":
        status = str(_get(data_obj, "status") or "")
        customer = _get(data_obj, "customer")
        if customer and status in ("canceled", "unpaid", "incomplete_expired"):
            db.set_plan_by_stripe_customer(str(customer), "free")
        elif customer and status in ("active", "trialing"):
            db.set_plan_by_stripe_customer(str(customer), "pro")

    return {"ok": True}


def _quota_402(remaining: float) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={
            "code": "quota_exceeded",
            "remaining_seconds": round(float(remaining), 2),
            "checkout_hint": "POST /v1/checkout with your cloud token, or upgrade to Pro",
            "message": "Whisper Cloud free minutes are used up for this month.",
        },
    )


@app.post("/openai/v1/audio/transcriptions")
def transcribe(
    file: UploadFile = File(..., description="WAV и т.д., как у Groq"),
    model: str = Form(...),
    response_format: str = Form(default="json"),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
    x_whisper_groq_proxy_secret: str | None = Header(
        default=None, alias="X-Whisper-Groq-Proxy-Secret"
    ),
    x_whisper_cloud_token: str | None = Header(default=None, alias="X-Whisper-Cloud-Token"),
) -> Response:
    bearer = cloud_auth.extract_bearer(authorization)
    ops = cloud_auth.is_ops_secret(x_whisper_groq_proxy_secret)
    cloud_hdr = (x_whisper_cloud_token or "").strip()
    cloud_tok = cloud_hdr if cloud_auth.is_cloud_token(cloud_hdr) else (
        bearer if cloud_auth.is_cloud_token(bearer) else ""
    )
    byok = bearer if cloud_auth.is_groq_key(bearer) else None

    # Auth modes:
    # 1) BYOK gsk_… → pass through, no metering
    # 2) Cloud wsk_… → meter + SERVER_KEY
    # 3) Ops PROXY_SHARED_SECRET → SERVER_KEY, no metering
    # 4) Legacy: no bearer but shared secret already checked; or empty SHARED + SERVER_KEY
    #    requires cloud token for public metering (when SHARED set, secret alone still ops)

    meter_token: str | None = None
    if byok:
        groq_auth = f"Bearer {byok}"
    elif cloud_tok:
        meter_token = cloud_tok
        if not SERVER_KEY:
            raise HTTPException(status_code=503, detail="Proxy GROQ_API_KEY not configured")
        groq_auth = f"Bearer {SERVER_KEY}"
    elif ops:
        if not SERVER_KEY:
            raise HTTPException(status_code=503, detail="Proxy GROQ_API_KEY not configured")
        groq_auth = f"Bearer {SERVER_KEY}"
    elif cloud_auth.SHARED:
        # Shared secret configured: require secret or cloud/BYOK (already failed above)
        raise HTTPException(
            status_code=401,
            detail="Need X-Whisper-Cloud-Token (wsk_…), BYOK Bearer gsk_…, or proxy secret",
        )
    else:
        # No shared secret: require cloud token for hosted key
        if not SERVER_KEY:
            raise HTTPException(
                status_code=401,
                detail="Proxy: set GROQ_API_KEY or send Authorization: Bearer from client",
            )
        raise HTTPException(
            status_code=401,
            detail="Register via POST /v1/devices/register and send X-Whisper-Cloud-Token",
        )

    raw = file.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    audio_sec = estimate_audio_seconds(raw, file.filename)
    if meter_token:
        try:
            db.assert_can_transcribe(meter_token, audio_sec)
        except LookupError as e:
            raise HTTPException(status_code=401, detail="Invalid cloud token") from e
        except PermissionError as e:
            return _quota_402(float(e.args[0]) if e.args else 0.0)

    fn = file.filename or "audio.wav"
    ct = file.content_type or "audio/wav"
    files = {"file": (fn, raw, ct)}
    data: dict[str, str] = {"model": model, "response_format": response_format}
    if language:
        data["language"] = language
    if prompt and str(prompt).strip():
        data["prompt"] = str(prompt).strip()

    try:
        r = requests.post(
            GROQ_TRANSCRIPTIONS,
            headers={
                "Authorization": groq_auth,
                "Accept": "application/json",
                "User-Agent": "WhisperGroqProxy/2.0",
            },
            files=files,
            data=data,
            timeout=(60.0, 600.0),
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Groq upstream: {e}") from e

    if meter_token and 200 <= r.status_code < 300:
        try:
            db.consume_usage(meter_token, audio_sec)
        except PermissionError as e:
            return _quota_402(float(e.args[0]) if e.args else 0.0)
        except LookupError:
            pass

    ct_out = r.headers.get("content-type", "application/json")
    return Response(content=r.content, status_code=r.status_code, media_type=ct_out)
