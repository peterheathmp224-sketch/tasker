"""Shared helpers: current user from X-Telegram-Init-Data header, task serialization."""
import os
from fastapi import Header, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from .database import get_db
from . import models
from .auth import validate_init_data, mock_user, verify_session_token

# Мок-юзер только когда явно включён (DEV_MOCK_USER=true, локальная разработка).
# Без валидного Telegram initData и без мока — 401, никого в БД не создаём.
DEV_MOCK = os.getenv("DEV_MOCK_USER", "true").lower() == "true"


def get_current_user(
    x_telegram_init_data: str = Header(default=""),
    initData: str = Query(default=""),
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> models.User:
    # Порядок: 1) Mini App initData, 2) сессия браузерного входа (Bearer),
    # 3) мок для локальной разработки. Иначе — 401, никого не создаём.
    # initData query-параметр — для скачивания файлов через openLink во внешнем
    # браузере, куда заголовки не передать. Заголовок в приоритете.
    raw = x_telegram_init_data or initData
    tg = validate_init_data(raw) if raw else None
    fresh_profile = tg is not None
    if tg is None and authorization.lower().startswith("bearer "):
        uid = verify_session_token(authorization[7:].strip())
        if uid is not None:
            # Профиль из сессии не обновляем (там только id) — догрузим из БД ниже.
            tg = {"id": uid}
    if tg is None:
        if DEV_MOCK:
            tg = mock_user()
            fresh_profile = True
        else:
            # Fail closed: никаких demo/guest юзеров в базе.
            raise HTTPException(401, "open the app via Telegram")
    try:
        uid = int(tg.get("id", 0))
    except (TypeError, ValueError):
        raise HTTPException(401, "open the app via Telegram")
    if uid <= 0:
        raise HTTPException(401, "open the app via Telegram")
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
        # refresh profile fields (без лишнего SELECT: refresh не нужен,
        # атрибуты уже выставлены; commit один на запрос максимум).
        # Сессионных юзеров (Bearer) не трогаем — в токене только id.
        if not fresh_profile:
            return user
        changed = False
        for k in ("username", "first_name", "photo_url"):
            v = tg.get(k, "") or ""
            if getattr(user, k) != v:
                setattr(user, k, v)
                changed = True
        if changed:
            db.commit()
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
    return serialize_tasks(db, [task])[0]


def serialize_tasks(db: Session, tasks: list[models.Task]) -> list[dict]:
    """Батчевая сериализация: ~4 SQL-запроса на весь список вместо 3-4 на задачу.

    Использует уже подгруженные (selectin) task.assignees / task.attachments,
    поэтому тела файлов (BYTEA, deferred) вообще не читаются — только метаданные.
    """
    if not tasks:
        return []
    # group_id -> group (один запрос)
    gids = {t.group_id for t in tasks if t.group_id}
    groups = db.query(models.Group).filter(models.Group.id.in_(gids)).all() if gids else []
    gmap = {g.id: g for g in groups}
    # group_id -> member user_ids (один запрос на все группы списка)
    group_members: dict[int, list[int]] = {}
    if gids:
        rows = db.query(models.GroupMember).filter(models.GroupMember.group_id.in_(gids)).all()
        for r in rows:
            group_members.setdefault(r.group_id, []).append(r.user_id)
    # все нужные пользователи — один запрос
    need_ids: set[int] = set()
    direct_map: dict[int, list[int]] = {}
    for t in tasks:
        ids = [a.user_id for a in (t.assignees or [])]
        direct_map[t.id] = ids
        need_ids.update(ids)
        if t.group_id and t.group_id in group_members:
            need_ids.update(group_members[t.group_id])
    users = db.query(models.User).filter(models.User.tg_id.in_(need_ids)).all() if need_ids else []
    umap = {u.tg_id: u for u in users}
    out = []
    for t in tasks:
        direct_ids = direct_map.get(t.id, [])
        direct = [umap[i] for i in direct_ids if i in umap]
        merged_ids: set[int] = set(direct_ids)
        if t.group_id and t.group_id in group_members:
            merged_ids.update(group_members[t.group_id])
        merged = [umap[i] for i in merged_ids if i in umap]
        g = gmap.get(t.group_id) if t.group_id else None
        out.append({
            "id": t.id,
            "title": t.title,
            "description": t.description or "",
            "deadline": t.deadline,
            "status": t.status,
            "group_id": t.group_id,
            "group_name": g.name if g else None,
            "created_by": t.created_by,
            # assignees — только прямые исполнители (их можно откреплять);
            # executors — прямые + участники группы (для отображения).
            "assignees": [_user_out(u) for u in direct],
            "assignee_ids": [u.tg_id for u in direct],
            "executors": [_user_out(u) for u in merged],
            # a.data (BYTEA) не трогаем — deferred, читаются только метаданные
            "attachments": [_attachment_out(a) for a in (t.attachments or [])],
        })
    return out
