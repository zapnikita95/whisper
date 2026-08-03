"""Auth helpers for Whisper Cloud tokens and legacy proxy secret."""
from __future__ import annotations

import os
from typing import Any

SHARED = (os.environ.get("PROXY_SHARED_SECRET") or "").strip()


def extract_bearer(authorization: str | None) -> str | None:
    auth = (authorization or "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    return auth[7:].strip() or None


def is_cloud_token(token: str | None) -> bool:
    return bool(token) and token.startswith("wsk_")


def is_groq_key(token: str | None) -> bool:
    return bool(token) and token.startswith("gsk_")


def is_ops_secret(header_secret: str | None) -> bool:
    if not SHARED:
        return False
    return (header_secret or "").strip() == SHARED


def public_me_payload(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": snap["device_id"],
        "token": snap["token"],
        "plan": snap["plan"],
        "period": snap["period"],
        "used_seconds": snap["used_seconds"],
        "quota_seconds": snap["quota_seconds"],
        "remaining_seconds": snap["remaining_seconds"],
        "remaining_minutes": snap["remaining_minutes"],
    }
