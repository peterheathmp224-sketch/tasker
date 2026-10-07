"""Браузерный вход через Telegram Login Widget + публичный конфиг для фронта."""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth import BOT_TOKEN, mint_session_token, validate_widget_data

router = APIRouter(prefix="/api/auth", tags=["auth"])


class WidgetAuthIn(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    photo_url: str = ""
    auth_date: int = 0
    hash: str = ""


def _widget_enabled() -> tuple[bool, str]:
    bot = os.getenv("BOT_USERNAME", "").lstrip("@")
    token = os.getenv("BOT_TOKEN", "") or BOT_TOKEN
    ok = bool(bot) and bool(token) and "PUT-YOUR-TOKEN" not in token
    return ok, bot


@router.get("/config")
def auth_config():
    ok, bot = _widget_enabled()
    return {"widget_enabled": ok, "bot_username": bot or None}


@router.post("/widget")
def login_widget(payload: WidgetAuthIn, db: Session = Depends(get_db)):
    ok, _ = _widget_enabled()
    if not ok:
        raise HTTPException(503, "telegram login is not configured (BOT_USERNAME/BOT_TOKEN)")
    tg = validate_widget_data(payload.model_dump())
    if tg is None:
        raise HTTPException(401, "bad telegram signature")
    uid = int(tg["id"])
    user = db.get(models.User, uid)
    if not user:
        user = models.User(
            tg_id=uid,
            username=tg.get("username", ""),
            first_name=tg.get("first_name", ""),
            photo_url=tg.get("photo_url", ""),
        )
        db.add(user)
        db.commit()
    else:
        changed = False
        for k in ("username", "first_name", "photo_url"):
            v = tg.get(k, "") or ""
            if getattr(user, k) != v:
                setattr(user, k, v)
                changed = True
        if changed:
            db.commit()
    token = mint_session_token(uid)
    return {
        "token": token,
        "user": {"tg_id": user.tg_id, "username": user.username, "first_name": user.first_name, "photo_url": user.photo_url},
    }
