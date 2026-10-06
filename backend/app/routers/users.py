from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..deps import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return {"tg_id": user.tg_id, "username": user.username, "first_name": user.first_name, "photo_url": user.photo_url}


@router.get("")
def list_users(search: str = "", db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    q = db.query(models.User)
    if search:
        s = f"%{search.strip().lstrip('@').lower()}%"
        q = q.filter(models.User.username.ilike(s))
    return [
        {"tg_id": u.tg_id, "username": u.username, "first_name": u.first_name, "photo_url": u.photo_url}
        for u in q.limit(50).all()
    ]
