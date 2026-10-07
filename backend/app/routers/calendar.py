from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..deps import get_current_user, serialize_tasks

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("")
def calendar(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    scope: str = "all", group_id: int | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    # scope=group: без group_id показываем задачи ВСЕХ групп пользователя,
    # с group_id — только этой группы.
    q = db.query(models.Task).filter(models.Task.deadline.is_not(None))
    if from_:
        q = q.filter(models.Task.deadline >= from_)
    if to:
        q = q.filter(models.Task.deadline <= to)
    if scope == "group":
        if group_id is not None:
            q = q.filter(models.Task.group_id == group_id)
        else:
            my_gids = select(models.GroupMember.group_id).where(models.GroupMember.user_id == user.tg_id).scalar_subquery()
            q = q.filter(models.Task.group_id.in_(my_gids))
    elif scope == "me":
        # Фильтр в SQL до сериализации: раньше сериализовался весь месяц, потом отбрасывалось.
        my_tasks = select(models.TaskAssignee.task_id).where(models.TaskAssignee.user_id == user.tg_id).scalar_subquery()
        q = q.filter(models.Task.id.in_(my_tasks))
    tasks = q.order_by(models.Task.deadline).limit(limit).all()
    out = serialize_tasks(db, tasks)
    by_date: dict[str, list] = {}
    for t in out:
        by_date.setdefault(str(t["deadline"]), []).append(t)
    return by_date
