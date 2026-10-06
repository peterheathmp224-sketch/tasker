from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..deps import get_current_user, serialize_task, task_executors

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _my_group_ids(db: Session, user: models.User) -> list[int]:
    rows = db.query(models.GroupMember).filter_by(user_id=user.tg_id).all()
    return [r.group_id for r in rows]


@router.get("")
def calendar(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    scope: str = "all", group_id: int | None = None,
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    # scope=group: без group_id показываем задачи ВСЕХ групп пользователя,
    # с group_id — только этой группы.
    if scope == "group" and group_id is None:
        gids = _my_group_ids(db, user)
        if not gids:
            return {}
    q = db.query(models.Task).filter(models.Task.deadline.is_not(None))
    if from_:
        q = q.filter(models.Task.deadline >= from_)
    if to:
        q = q.filter(models.Task.deadline <= to)
    if scope == "group":
        if group_id is not None:
            q = q.filter(models.Task.group_id == group_id)
        else:
            q = q.filter(models.Task.group_id.in_(gids))
    tasks = q.order_by(models.Task.deadline).all()
    out = []
    for t in tasks:
        s = serialize_task(db, t)
        # s["assignees"] — только прямые исполнители (см. serialize_task)
        if scope == "me" and not any(a["tg_id"] == user.tg_id for a in s["assignees"]):
            continue
        out.append(s)
    by_date: dict[str, list] = {}
    for t in out:
        by_date.setdefault(str(t["deadline"]), []).append(t)
    return by_date
