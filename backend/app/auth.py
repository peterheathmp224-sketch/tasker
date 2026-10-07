"""Validate Telegram WebApp initData. See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Сессии браузерного входа (Login Widget): stateless HMAC-токены, 30 суток.
SESSION_TTL_SECONDS = 30 * 24 * 3600
# Widget-данные старше суток не принимаем (требование Telegram).
WIDGET_TTL_SECONDS = 24 * 3600


def validate_init_data(init_data: str) -> dict | None:
    """Return telegram user dict if valid, else None. Empty/BOT_TOKEN placeholder => None."""
    token = (os.getenv("BOT_TOKEN", "") or BOT_TOKEN).strip()
    if not init_data or not token or "PUT-YOUR-TOKEN" in token:
        return None
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        recv_hash = pairs.pop("hash", "")
        data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None
        return json.loads(pairs.get("user", "{}"))
    except Exception:
        return None


def mock_user() -> dict:
    return {"id": 1, "username": "demo", "first_name": "Demo", "photo_url": ""}


def validate_widget_data(data: dict) -> dict | None:
    """Проверка данных Telegram Login Widget (браузерный вход).

    См. https://core.telegram.org/widgets/login#checking-authorization
    Возвращает dict юзера при валидной подписи, иначе None.
    """
    token = (os.getenv("BOT_TOKEN", "") or BOT_TOKEN).strip()
    if not data or not token or "PUT-YOUR-TOKEN" in token:
        return None
    try:
        recv_hash = str(data.get("hash", ""))
        auth_date = int(data.get("auth_date", 0) or 0)
        if not recv_hash or auth_date <= 0:
            return None
        now = int(time.time())
        if auth_date > now + 300 or now - auth_date > WIDGET_TTL_SECONDS:
            return None
        # Только присланные поля (без hash). Пустые дефолты сюда попадать не должны —
        # вызывающий код передает exclude_unset=True.
        check = "\n".join(f"{k}={data[k]}" for k in sorted(data) if k != "hash" and data[k] is not None)
        secret = hashlib.sha256(token.encode()).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None
        uid = int(data.get("id", 0))
        if uid <= 0:
            return None
        return {
            "id": uid,
            "username": str(data.get("username") or ""),
            "first_name": str(data.get("first_name") or ""),
            "last_name": str(data.get("last_name") or ""),
            "photo_url": str(data.get("photo_url") or ""),
        }
    except (ValueError, TypeError):
        return None


def _session_secret() -> bytes:
    # Отдельный секрет лучше (SESSION_SECRET), иначе деривация из токена бота.
    return (os.getenv("SESSION_SECRET", "") or BOT_TOKEN).encode()


def mint_session_token(tg_id: int, ttl: int = SESSION_TTL_SECONDS) -> str:
    """Stateless сессия: 'tg_id.exp.hmac'. Хранить негде не надо, валидация по HMAC."""
    exp = int(time.time()) + ttl
    body = f"{tg_id}.{exp}".encode()
    sig = hmac.new(_session_secret(), body, hashlib.sha256).hexdigest()
    return f"{tg_id}.{exp}.{sig}"


def verify_session_token(token: str) -> int | None:
    """Возвращает tg_id при валидном непросроченном токене, иначе None."""
    try:
        if not token or token.count(".") != 2:
            return None
        tg_id_s, exp_s, sig = token.split(".")
        want = hmac.new(_session_secret(), f"{tg_id_s}.{exp_s}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want, sig):
            return None
        if int(exp_s) < int(time.time()):
            return None
        uid = int(tg_id_s)
        return uid if uid > 0 else None
    except (ValueError, TypeError):
        return None
