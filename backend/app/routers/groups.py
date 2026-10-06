from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..deps import get_current_user

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _out(db: Session, g: models.Group) -> dict:
    ids = [m.user_id for m in db.query(models.GroupMember).filter_by(group_id=g.id).all()]
    users = db.query(models.User).filter(models.User.tg_id.in_(ids)).all() if ids else []
    return {
        "id": g.id, "name": g.name,
        "members": [{"tg_id": u.tg_id, "username": u.username, "first_name": u.first_name, "photo_url": u.photo_url} for u in users],
    }


@router.get("")
def list_groups(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return [_out(db, g) for g in db.query(models.Group).order_by(models.Group.id).all()]


@router.post("", status_code=201)
def create_group(payload: schemas.GroupCreate, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    g = models.Group(name=payload.name)
    db.add(g)
    db.commit()
    db.refresh(g)
    return _out(db, g)


@router.delete("/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    g = db.get(models.Group, group_id)
    if not g:
        raise HTTPException(404, "not found")
    # unlink tasks (SET NULL), don't delete them
    db.query(models.Task).filter_by(group_id=group_id).update({"group_id": None})
    db.query(models.GroupMember).filter_by(group_id=group_id).delete()
    db.delete(g)
    db.commit()
    return {"ok": True}


@router.post("/{group_id}/members")
def add_member(group_id: int, payload: schemas.MemberAdd, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
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
    return _out(db, g)


@router.delete("/{group_id}/members/{user_id}")
def remove_member(group_id: int, user_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    db.query(models.GroupMember).filter_by(group_id=group_id, user_id=user_id).delete()
    db.commit()
    g = db.get(models.Group, group_id)
    return _out(db, g) if g else {"ok": True}
