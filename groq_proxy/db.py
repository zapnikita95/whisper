"""SQLite storage for Whisper Cloud tokens, plans, and usage metering."""
from __future__ import annotations

import os
import sqlite3
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

FREE_SECONDS_PER_MONTH = int(os.environ.get("WHISPER_CLOUD_FREE_SECONDS", str(30 * 60)))
PRO_SOFT_CAP_SECONDS = int(os.environ.get("WHISPER_CLOUD_PRO_SOFT_CAP_SECONDS", str(2000 * 60)))

_lock = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _period_key(dt: datetime | None = None) -> str:
    d = dt or _utc_now()
    return f"{d.year:04d}-{d.month:02d}"


def db_path() -> Path:
    env = (os.environ.get("WHISPER_CLOUD_DB_PATH") or "").strip()
    if env:
        return Path(env)
    railway = Path("/data")
    if railway.is_dir() and os.access(railway, os.W_OK):
        return railway / "whisper_cloud.db"
    return Path(__file__).resolve().parent / "whisper_cloud.db"


def init_db() -> None:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL UNIQUE,
                plan TEXT NOT NULL DEFAULT 'free',
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                period TEXT NOT NULL,
                used_seconds REAL NOT NULL DEFAULT 0,
                UNIQUE(device_id, period)
            );
            CREATE INDEX IF NOT EXISTS idx_devices_token ON devices(token);
            """
        )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_path()), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _new_token() -> str:
    return "wsk_" + secrets.token_urlsafe(32)


def register_device(device_id: str) -> dict[str, Any]:
    device_id = (device_id or "").strip()
    if not device_id or len(device_id) > 128:
        raise ValueError("invalid device_id")
    now = _utc_now().isoformat()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row:
                return _device_snapshot(conn, dict(row))
            token = _new_token()
            conn.execute(
                """
                INSERT INTO devices (device_id, token, plan, created_at, updated_at)
                VALUES (?, ?, 'free', ?, ?)
                """,
                (device_id, token, now, now),
            )
            conn.execute(
                """
                INSERT INTO usage_periods (device_id, period, used_seconds)
                VALUES (?, ?, 0)
                """,
                (device_id, _period_key()),
            )
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            return _device_snapshot(conn, dict(row))


def get_by_token(token: str) -> dict[str, Any] | None:
    token = (token or "").strip()
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM devices WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        return _device_snapshot(conn, dict(row))


def set_plan(
    *,
    device_id: str | None = None,
    token: str | None = None,
    plan: str,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
) -> dict[str, Any] | None:
    if plan not in ("free", "pro"):
        raise ValueError("plan must be free or pro")
    now = _utc_now().isoformat()
    with _lock:
        with _connect() as conn:
            if token:
                row = conn.execute("SELECT * FROM devices WHERE token = ?", (token,)).fetchone()
            elif device_id:
                row = conn.execute(
                    "SELECT * FROM devices WHERE device_id = ?", (device_id,)
                ).fetchone()
            else:
                return None
            if not row:
                return None
            did = row["device_id"]
            conn.execute(
                """
                UPDATE devices SET plan = ?, stripe_customer_id = COALESCE(?, stripe_customer_id),
                  stripe_subscription_id = COALESCE(?, stripe_subscription_id), updated_at = ?
                WHERE device_id = ?
                """,
                (plan, stripe_customer_id, stripe_subscription_id, now, did),
            )
            if plan == "free":
                conn.execute(
                    """
                    UPDATE devices SET stripe_subscription_id = NULL, updated_at = ?
                    WHERE device_id = ?
                    """,
                    (now, did),
                )
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (did,)).fetchone()
            return _device_snapshot(conn, dict(row))


def set_plan_by_stripe_customer(customer_id: str, plan: str) -> dict[str, Any] | None:
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE stripe_customer_id = ?", (customer_id,)
            ).fetchone()
            if not row:
                return None
    return set_plan(device_id=row["device_id"], plan=plan)


def grant_pro_by_token(token: str) -> dict[str, Any] | None:
    return set_plan(token=token, plan="pro")


def _used_seconds(conn: sqlite3.Connection, device_id: str, period: str) -> float:
    row = conn.execute(
        "SELECT used_seconds FROM usage_periods WHERE device_id = ? AND period = ?",
        (device_id, period),
    ).fetchone()
    return float(row["used_seconds"]) if row else 0.0


def _ensure_period(conn: sqlite3.Connection, device_id: str, period: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO usage_periods (device_id, period, used_seconds)
        VALUES (?, ?, 0)
        """,
        (device_id, period),
    )


def _quota_for_plan(plan: str) -> float:
    if plan == "pro":
        return float(PRO_SOFT_CAP_SECONDS)
    return float(FREE_SECONDS_PER_MONTH)


def _device_snapshot(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    period = _period_key()
    _ensure_period(conn, row["device_id"], period)
    used = _used_seconds(conn, row["device_id"], period)
    plan = row["plan"] or "free"
    quota = _quota_for_plan(plan)
    remaining = max(0.0, quota - used)
    return {
        "device_id": row["device_id"],
        "token": row["token"],
        "plan": plan,
        "period": period,
        "used_seconds": round(used, 2),
        "quota_seconds": quota,
        "remaining_seconds": round(remaining, 2),
        "remaining_minutes": round(remaining / 60.0, 2),
        "stripe_customer_id": row.get("stripe_customer_id"),
        "stripe_subscription_id": row.get("stripe_subscription_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def assert_can_transcribe(token: str, audio_seconds: float) -> dict[str, Any]:
    """Raises PermissionError with remaining_seconds if over quota."""
    snap = get_by_token(token)
    if not snap:
        raise LookupError("invalid cloud token")
    need = max(0.1, float(audio_seconds))
    if snap["remaining_seconds"] < need:
        raise PermissionError(snap["remaining_seconds"])
    return snap


def consume_usage(token: str, audio_seconds: float) -> dict[str, Any]:
    need = max(0.1, float(audio_seconds))
    period = _period_key()
    with _lock:
        with _connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE token = ?", (token,)).fetchone()
            if not row:
                raise LookupError("invalid cloud token")
            did = row["device_id"]
            plan = row["plan"] or "free"
            quota = _quota_for_plan(plan)
            _ensure_period(conn, did, period)
            used = _used_seconds(conn, did, period)
            if used + need > quota + 0.01:
                raise PermissionError(max(0.0, quota - used))
            conn.execute(
                """
                UPDATE usage_periods SET used_seconds = used_seconds + ?
                WHERE device_id = ? AND period = ?
                """,
                (need, did, period),
            )
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (did,)).fetchone()
            return _device_snapshot(conn, dict(row))
