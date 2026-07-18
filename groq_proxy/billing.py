"""Stripe Checkout + webhooks for Whisper Cloud Pro."""
from __future__ import annotations

import os
from typing import Any

STRIPE_SECRET_KEY = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
STRIPE_WEBHOOK_SECRET = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
STRIPE_PRICE_PRO_MONTHLY = (os.environ.get("STRIPE_PRICE_PRO_MONTHLY") or "").strip()
PUBLIC_BASE_URL = (os.environ.get("WHISPER_CLOUD_PUBLIC_URL") or "").strip().rstrip("/")
SUCCESS_URL = (os.environ.get("STRIPE_SUCCESS_URL") or "").strip()
CANCEL_URL = (os.environ.get("STRIPE_CANCEL_URL") or "").strip()


def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_PRO_MONTHLY)


def _default_success() -> str:
    if SUCCESS_URL:
        return SUCCESS_URL
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/?checkout=success"
    return "https://zapnikita95.github.io/whisper/?checkout=success"


def _default_cancel() -> str:
    if CANCEL_URL:
        return CANCEL_URL
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/?checkout=cancel"
    return "https://zapnikita95.github.io/whisper/?checkout=cancel"


def create_checkout_session(*, cloud_token: str, device_id: str, customer_id: str | None) -> dict[str, Any]:
    if not stripe_configured():
        raise RuntimeError("Stripe not configured (STRIPE_SECRET_KEY / STRIPE_PRICE_PRO_MONTHLY)")
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    kwargs: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": STRIPE_PRICE_PRO_MONTHLY, "quantity": 1}],
        "success_url": _default_success(),
        "cancel_url": _default_cancel(),
        "client_reference_id": device_id,
        "metadata": {"device_id": device_id, "cloud_token_prefix": cloud_token[:12]},
        "subscription_data": {"metadata": {"device_id": device_id}},
    }
    if customer_id:
        kwargs["customer"] = customer_id
    else:
        kwargs["customer_creation"] = "always"
    session = stripe.checkout.Session.create(**kwargs)
    return {"checkout_url": session.url, "session_id": session.id}


def construct_webhook_event(payload: bytes, sig_header: str | None) -> Any:
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("Stripe not configured")
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    if STRIPE_WEBHOOK_SECRET:
        return stripe.Webhook.construct_event(payload, sig_header or "", STRIPE_WEBHOOK_SECRET)
    # Dev fallback when webhook secret unset: parse JSON without verify (Railway local tests).
    import json

    return json.loads(payload.decode("utf-8"))
