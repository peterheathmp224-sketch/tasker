from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..deps import get_current_user
from .. import notify

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _out(db: Session, g: models.Group) -> dict:
    return _out_many(db, [g])[0]


def _out_many(db: Session, groups: list[models.Group]) -> list[dict]:
    """Батч: 2 запроса на весь список групп вместо 2N."""
    if not groups:
        return []
    gids = [g.id for g in groups]
    rows = db.query(models.GroupMember).filter(models.GroupMember.group_id.in_(gids)).all()
    by_group: dict[int, list[int]] = {}
    all_ids: set[int] = set()
    for r in rows:
        by_group.setdefault(r.group_id, []).append(r.user_id)
        all_ids.add(r.user_id)
    users = db.query(models.User).filter(models.User.tg_id.in_(all_ids)).all() if all_ids else []
    umap = {u.tg_id: u for u in users}
    return [
        {
            "id": g.id, "name": g.name,
            "members": [
                {"tg_id": umap[i].tg_id, "username": umap[i].username,
                 "first_name": umap[i].first_name, "photo_url": umap[i].photo_url}
                for i in by_group.get(g.id, []) if i in umap
            ],
        }
        for g in groups
    ]


@router.get("")
def list_groups(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return _out_many(db, db.query(models.Group).order_by(models.Group.id).all())


@router.post("", status_code=201)
def create_group(payload: schemas.GroupCreate, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    g = models.Group(name=payload.name)
    db.add(g)
    db.commit()
    return _out(db, g)


@router.delete("/{group_id}")
def delete_group(group_id: int, bg: BackgroundTasks, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    g = db.get(models.Group, group_id)
    if not g:
        raise HTTPException(404, "not found")
    name = g.name
    recips = notify.group_members(db, group_id) - {user.tg_id}
    # unlink tasks (SET NULL), don't delete them
    db.query(models.Task).filter_by(group_id=group_id).update({"group_id": None})
    db.query(models.GroupMember).filter_by(group_id=group_id).delete()
    db.delete(g)
    db.commit()
    if recips:
        bg.add_task(notify.broadcast, sorted(recips), notify.group_deleted(name, notify.actor_out(user)))
    return {"ok": True}


@router.post("/{group_id}/members")
def add_member(group_id: int, payload: schemas.MemberAdd, bg: BackgroundTasks, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    g = db.get(models.Group, group_id)
    if not g:
        raise HTTPException(404, "group not found")
    uid = payload.user_id
    if uid is None and payload.username:
        u = db.query(models.User).filter(models.User.username.ilike(payload.username.strip().lstrip("@"))).first()
        if not u:
            raise HTTPException(404, "user not found, invite them to open the app first")
        uid = u.tg_id
    if uid is None:
        raise HTTPException(400, "user_id or username required")
    if not db.get(models.User, uid):
        db.add(models.User(tg_id=uid))
        db.commit()
    if not db.query(models.GroupMember).filter_by(group_id=group_id, user_id=uid).first():
        db.add(models.GroupMember(group_id=group_id, user_id=uid))
        db.commit()
        if uid != user.tg_id:
            bg.add_task(notify.send_message, uid, notify.group_member_added(g.name, notify.actor_out(user)))
    return _out(db, g)


@router.delete("/{group_id}/members/{user_id}")
def remove_member(group_id: int, user_id: int, bg: BackgroundTasks, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    db.query(models.GroupMember).filter_by(group_id=group_id, user_id=user_id).delete()
    db.commit()
    g = db.get(models.Group, group_id)
    if user_id != user.tg_id:
        bg.add_task(notify.send_message, user_id, notify.group_member_removed(g.name if g else "", notify.actor_out(user)))
    return _out(db, g) if g else {"ok": True}
