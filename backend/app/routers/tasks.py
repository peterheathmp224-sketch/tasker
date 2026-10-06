from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..deps import get_current_user, serialize_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 МБ — файлы хранятся в БД (BYTEA), больше не кладём


def _ensure_users(db: Session, ids: list[int]):
    for uid in ids:
        if not db.get(models.User, uid):
            db.add(models.User(tg_id=uid))
    db.commit()


@router.get("")
def list_tasks(
    assignee: str = "", status: str = "", group_id: int | None = None, scope: str = "",
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    q = db.query(models.Task)
    if group_id is not None:
        q = q.filter(models.Task.group_id == group_id)
    elif scope == "group":
        # без group_id — задачи всех групп пользователя (для календаря scope=Группа)
        gids = [r.group_id for r in db.query(models.GroupMember).filter_by(user_id=user.tg_id).all()]
        if not gids:
            return []
        q = q.filter(models.Task.group_id.in_(gids))
    if status:
        q = q.filter(models.Task.status == status)
    tasks = q.order_by(models.Task.deadline.is_(None), models.Task.deadline).all()
    out = [serialize_task(db, t) for t in tasks]
    if assignee == "me":
        # только прямые исполнители (t["assignees"] — direct, см. serialize_task)
        out = [t for t in out if any(a["tg_id"] == user.tg_id for a in t["assignees"])]
    return out


@router.post("", status_code=201)
def create_task(payload: schemas.TaskCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if payload.status not in schemas.STATUSES:
        raise HTTPException(400, "bad status")
    t = models.Task(
        title=payload.title, description=payload.description or "",
        deadline=payload.deadline, status=payload.status,
        group_id=payload.group_id, created_by=user.tg_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    if payload.assignee_ids:
        _ensure_users(db, payload.assignee_ids)
        for uid in set(payload.assignee_ids):
            db.add(models.TaskAssignee(task_id=t.id, user_id=uid))
        db.commit()
        db.refresh(t)
    return serialize_task(db, t)


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "not found")
    return serialize_task(db, t)


@router.patch("/{task_id}")
def update_task(task_id: int, payload: schemas.TaskUpdate, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    # anyone can edit (v1 rule)
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "not found")
    data = payload.model_dump(exclude_unset=True)
    assignees = data.pop("assignee_ids", None)
    if "status" in data and data["status"] not in schemas.STATUSES:
        raise HTTPException(400, "bad status")
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    if assignees is not None:
        _ensure_users(db, assignees)
        db.query(models.TaskAssignee).filter_by(task_id=t.id).delete()
        for uid in set(assignees):
            db.add(models.TaskAssignee(task_id=t.id, user_id=uid))
        db.commit()
        db.refresh(t)
    return serialize_task(db, t)


@router.delete("/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "not found")
    db.query(models.TaskAssignee).filter_by(task_id=t.id).delete()
    db.query(models.TaskAttachment).filter_by(task_id=t.id).delete()
    db.delete(t)
    db.commit()
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
    db.refresh(a)
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
