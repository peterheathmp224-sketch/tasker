"""Shared helpers: current user from X-Telegram-Init-Data header, task serialization."""
import os
from fastapi import Header, Depends
from sqlalchemy.orm import Session
from .database import get_db
from . import models
from .auth import validate_init_data, mock_user

DEV_MOCK = os.getenv("DEV_MOCK_USER", "true").lower() == "true"


def get_current_user(x_telegram_init_data: str = Header(default=""), db: Session = Depends(get_db)) -> models.User:
    tg = validate_init_data(x_telegram_init_data) if x_telegram_init_data else None
    if tg is None and DEV_MOCK:
        tg = mock_user()
    if tg is None:
        # fallback guest (lets local dev without telegram work)
        tg = mock_user()
    uid = int(tg.get("id", 1))
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
        db.refresh(user)
    else:
        # refresh profile fields
        changed = False
        for k in ("username", "first_name", "photo_url"):
            v = tg.get(k, "") or ""
            if getattr(user, k) != v:
                setattr(user, k, v)
                changed = True
        if changed:
            db.commit()
            db.refresh(user)
    return user


def task_assignees(db: Session, task: models.Task) -> list[models.User]:
    """Только прямые исполнители задачи (таблица task_assignees)."""
    ids = {a.user_id for a in task.assignees}
    users = db.query(models.User).filter(models.User.tg_id.in_(ids)).all() if ids else []
    return users


def task_executors(db: Session, task: models.Task) -> list[models.User]:
    """Прямые исполнители + участники группы задачи (для отображения/совместимости)."""
    ids: set[int] = set()
    for a in task.assignees:
        ids.add(a.user_id)
    group_name = None
    if task.group_id:
        rows = db.query(models.GroupMember).filter_by(group_id=task.group_id).all()
        ids.update(r.user_id for r in rows)
    users = db.query(models.User).filter(models.User.tg_id.in_(ids)).all() if ids else []
    return users


def _user_out(u: models.User) -> dict:
    return {"tg_id": u.tg_id, "username": u.username, "first_name": u.first_name, "photo_url": u.photo_url}


def _attachment_out(a: "models.TaskAttachment") -> dict:
    return {
        "id": a.id,
        "task_id": a.task_id,
        "filename": a.filename,
        "content_type": a.content_type or "application/octet-stream",
        "size": a.size or 0,
        "uploaded_by": a.uploaded_by,
        "url": f"/api/tasks/{a.task_id}/attachments/{a.id}",
    }


def serialize_task(db: Session, task: models.Task) -> dict:
    direct = task_assignees(db, task)
    merged = task_executors(db, task)
    gname = None
    if task.group_id:
        g = db.get(models.Group, task.group_id)
        gname = g.name if g else None
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description or "",
        "deadline": task.deadline,
        "status": task.status,
        "group_id": task.group_id,
        "group_name": gname,
        "created_by": task.created_by,
        # assignees — только прямые исполнители (их можно откреплять);
        # executors — прямые + участники группы (для отображения).
        "assignees": [_user_out(u) for u in direct],
        "assignee_ids": [u.tg_id for u in direct],
        "executors": [_user_out(u) for u in merged],
        "attachments": [_attachment_out(a) for a in (task.attachments or [])],
    }
