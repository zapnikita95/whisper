#!/usr/bin/env python3
"""Grant or revoke Pro for a cloud token (manual billing).

Usage:
  python grant_pro.py wsk_...
  python grant_pro.py wsk_... --plan free
  WHISPER_CLOUD_ADMIN_SECRET=… python grant_pro.py --remote https://….railway.app wsk_...
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests


def main() -> int:
    p = argparse.ArgumentParser(description="Grant Whisper Cloud Pro")
    p.add_argument("token", help="Cloud token wsk_…")
    p.add_argument("--plan", default="pro", choices=("pro", "free"))
    p.add_argument("--remote", default="", help="Proxy base URL; if set, uses admin HTTP API")
    p.add_argument(
        "--admin-secret",
        default=os.environ.get("WHISPER_CLOUD_ADMIN_SECRET", ""),
        help="Admin secret for remote grant",
    )
    p.add_argument(
        "--db",
        default=os.environ.get("WHISPER_CLOUD_DB_PATH", ""),
        help="Local SQLite path (local mode)",
    )
    args = p.parse_args()
    token = args.token.strip()
    if not token.startswith("wsk_"):
        print("Token must start with wsk_", file=sys.stderr)
        return 2

    if args.remote:
        secret = (args.admin_secret or "").strip()
        if not secret:
            print("Need --admin-secret or WHISPER_CLOUD_ADMIN_SECRET", file=sys.stderr)
            return 2
        url = args.remote.rstrip("/") + "/v1/admin/grant-pro"
        r = requests.post(
            url,
            headers={"X-Whisper-Cloud-Admin-Secret": secret},
            json={"token": token, "plan": args.plan},
            timeout=30,
        )
        print(r.status_code, r.text)
        return 0 if r.status_code < 400 else 1

    if args.db:
        os.environ["WHISPER_CLOUD_DB_PATH"] = args.db
    import db

    db.init_db()
    snap = db.set_plan(token=token, plan=args.plan)
    if not snap:
        print("Device not found", file=sys.stderr)
        return 1
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
