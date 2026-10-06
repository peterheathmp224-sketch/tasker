"""Validate Telegram WebApp initData. See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
import hashlib
import hmac
import json
import os
import urllib.parse

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def validate_init_data(init_data: str) -> dict | None:
    """Return telegram user dict if valid, else None. Empty/BOT_TOKEN placeholder => None."""
    if not init_data or not BOT_TOKEN or "PUT-YOUR-TOKEN" in BOT_TOKEN:
        return None
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        recv_hash = pairs.pop("hash", "")
        data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None
        return json.loads(pairs.get("user", "{}"))
    except Exception:
        return None


def mock_user() -> dict:
    return {"id": 1, "username": "demo", "first_name": "Demo", "photo_url": ""}
