from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..deps import get_current_user, serialize_task, serialize_tasks
from .. import notify

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 МБ — файлы хранятся в БД (BYTEA), больше не кладём


def _ensure_users(db: Session, ids: list[int]):
    uniq = list(set(ids))
    if not uniq:
        return
    have = {r[0] for r in db.query(models.User.tg_id).filter(models.User.tg_id.in_(uniq)).all()}
    for uid in uniq:
        if uid not in have:
            db.add(models.User(tg_id=uid))
    db.commit()


@router.get("")
def list_tasks(
    assignee: str = "", status: str = "", group_id: int | None = None, scope: str = "",
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    q = db.query(models.Task)
    if group_id is not None:
        q = q.filter(models.Task.group_id == group_id)
    elif scope == "group":
        # без group_id — задачи всех групп пользователя.
        # Подзапрос вместо выгрузки всех memberships в Python.
        my_gids = select(models.GroupMember.group_id).where(models.GroupMember.user_id == user.tg_id).scalar_subquery()
        q = q.filter(models.Task.group_id.in_(my_gids))
    if status:
        q = q.filter(models.Task.status == status)
    if assignee == "me":
        # Только прямые исполнители — фильтруем в SQL ДО сериализации,
        # раньше грузились и сериализовались ВСЕ задачи, потом отбрасывались.
        my_tasks = select(models.TaskAssignee.task_id).where(models.TaskAssignee.user_id == user.tg_id).scalar_subquery()
        q = q.filter(models.Task.id.in_(my_tasks))
    tasks = q.order_by(models.Task.deadline.is_(None), models.Task.deadline).limit(limit).offset(offset).all()
    return serialize_tasks(db, tasks)


@router.post("", status_code=201)
def create_task(payload: schemas.TaskCreate, bg: BackgroundTasks, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if payload.status not in schemas.STATUSES:
        raise HTTPException(400, "bad status")
    t = models.Task(
        title=payload.title, description=payload.description or "",
        deadline=payload.deadline, status=payload.status,
        group_id=payload.group_id, created_by=user.tg_id,
    )
    db.add(t)
    db.commit()
    if payload.assignee_ids:
        _ensure_users(db, payload.assignee_ids)
        for uid in set(payload.assignee_ids):
            db.add(models.TaskAssignee(task_id=t.id, user_id=uid))
        db.commit()
    out = serialize_task(db, t)
    # Уведомление участникам (прямые исполнители + группа), кроме постановщика.
    recips = (set(payload.assignee_ids or []) | notify.group_members(db, payload.group_id)) - {user.tg_id}
    if recips:
        bg.add_task(notify.broadcast, sorted(recips), notify.task_created(out, notify.actor_out(user)))
    return out


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "not found")
    return serialize_task(db, t)


@router.patch("/{task_id}")
def update_task(task_id: int, payload: schemas.TaskUpdate, bg: BackgroundTasks, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    # anyone can edit (v1 rule)
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "not found")
    data = payload.model_dump(exclude_unset=True)
    assignees = data.pop("assignee_ids", None)
    if "status" in data and data["status"] not in schemas.STATUSES:
        raise HTTPException(400, "bad status")
    old_status, old_group, old_deadline = t.status, t.group_id, t.deadline
    old_assignees = {a.user_id for a in (t.assignees or [])}
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    if assignees is not None:
        _ensure_users(db, assignees)
        # Bulk-delete выполняется немедленным SQL (в отличие от db.delete(),
        # который откладывается до flush и бьётся о UNIQUE при замене состава).
        db.query(models.TaskAssignee).filter_by(task_id=t.id).delete()
        for uid in set(assignees):
            db.add(models.TaskAssignee(task_id=t.id, user_id=uid))
        db.commit()
        # Коллекция t.assignees в памяти протухла — один SELECT ради свежего чтения.
        db.expire(t, ["assignees"])
    new_assignees = set(assignees) if assignees is not None else old_assignees
    out = serialize_task(db, t)
    actor, me = notify.actor_out(user), user.tg_id
    jobs: list[tuple[set[int], str]] = []
    status_changed = "status" in data and data["status"] != old_status
    if status_changed:
        recips = notify.task_participants(db, t.id, t.group_id, t.created_by) - {me}
        jobs.append((recips, notify.task_status(out, actor, old_status, t.status)))
    if assignees is not None:
        added, removed = (new_assignees - old_assignees) - {me}, (old_assignees - new_assignees) - {me}
        if added:
            jobs.append((added, notify.task_assignee_added(out, actor)))
        if removed:
            jobs.append((removed, notify.task_assignee_removed(out, actor)))
    if "group_id" in data and t.group_id != old_group:
        if t.group_id:
            gname = notify.group_name(db, t.group_id)
            if gname:
                jobs.append((notify.group_members(db, t.group_id) - {me}, notify.task_group_attached(out, actor, gname)))
        if old_group:
            gname = notify.group_name(db, old_group)
            if gname:
                jobs.append((notify.group_members(db, old_group) - {me}, notify.task_group_detached(out, actor, gname)))
    if "deadline" in data and data["deadline"] != old_deadline and not status_changed:
        recips = notify.task_participants(db, t.id, t.group_id, t.created_by) - {me}
        jobs.append((recips, notify.task_deadline_changed(out, actor, old_deadline, t.deadline)))
    for recips, text in jobs:
        if recips:
            bg.add_task(notify.broadcast, sorted(recips), text)
    return out


@router.delete("/{task_id}")
def delete_task(task_id: int, bg: BackgroundTasks, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "not found")
    title, deadline = t.title, t.deadline
    recips = notify.task_participants(db, t.id, t.group_id, t.created_by) - {user.tg_id}
    # Исполнители и файлы удаляются каскадом (delete-orphan) — отдельных bulk-delete
    # не нужно (они же и давали двойное удаление + SAWarning).
    db.delete(t)
    db.commit()
    if recips:
        bg.add_task(notify.broadcast, sorted(recips), notify.task_deleted(title, deadline, notify.actor_out(user)))
    return {"ok": True}


# ---------- attachments (хранятся в БД) ----------

def _attachment_out(a: models.TaskAttachment) -> dict:
    return {
        "id": a.id,
        "task_id": a.task_id,
        "filename": a.filename,
        "content_type": a.content_type or "application/octet-stream",
        "size": a.size or 0,
        "uploaded_by": a.uploaded_by,
        "url": f"/api/tasks/{a.task_id}/attachments/{a.id}",
    }


@router.get("/{task_id}/attachments")
def list_attachments(task_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "task not found")
    rows = db.query(models.TaskAttachment).filter_by(task_id=task_id).order_by(models.TaskAttachment.id).all()
    return [_attachment_out(a) for a in rows]


@router.post("/{task_id}/attachments", status_code=201)
async def upload_attachment(
    task_id: int,
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "task not found")
    if not file.filename:
        raise HTTPException(400, "no filename")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, f"file too large (max {MAX_FILE_SIZE // 1024 // 1024} MB)")
    a = models.TaskAttachment(
        task_id=task_id,
        filename=file.filename[:255],
        content_type=file.content_type or "application/octet-stream",
        size=len(data),
        data=data,
        uploaded_by=user.tg_id,
    )
    db.add(a)
    db.commit()
    recips = notify.task_participants(db, t.id, t.group_id, t.created_by) - {user.tg_id}
    if recips:
        bg.add_task(
            notify.broadcast, sorted(recips),
            notify.file_uploaded({"title": t.title}, notify.actor_out(user), a.filename, a.size),
        )
    return _attachment_out(a)


@router.get("/{task_id}/attachments/{attachment_id}")
def download_attachment(
    task_id: int, attachment_id: int,
    db: Session = Depends(get_db), _: models.User = Depends(get_current_user),
):
    a = db.query(models.TaskAttachment).filter_by(id=attachment_id, task_id=task_id).first()
    if not a:
        raise HTTPException(404, "not found")
    # filename* для кириллицы
    from urllib.parse import quote
    disp = f"attachment; filename*=UTF-8''{quote(a.filename)}"
    return Response(
        content=bytes(a.data),
        media_type=a.content_type or "application/octet-stream",
        headers={"Content-Disposition": disp},
    )


@router.delete("/{task_id}/attachments/{attachment_id}")
def delete_attachment(
    task_id: int, attachment_id: int,
    db: Session = Depends(get_db), _: models.User = Depends(get_current_user),
):
    a = db.query(models.TaskAttachment).filter_by(id=attachment_id, task_id=task_id).first()
    if not a:
        raise HTTPException(404, "not found")
    db.delete(a)
    db.commit()
    return {"ok": True}
