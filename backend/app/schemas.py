from datetime import date
from typing import Optional
from pydantic import BaseModel

STATUSES = ("new", "in_progress", "done")


class UserOut(BaseModel):
    tg_id: int
    username: str = ""
    first_name: str = ""
    photo_url: str = ""

    class Config:
        from_attributes = True


class AuthIn(BaseModel):
    initData: str = ""


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    deadline: Optional[date] = None  # YYYY-MM-DD, date only
    status: str = "new"
    group_id: Optional[int] = None
    assignee_ids: list[int] = []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[date] = None
    status: Optional[str] = None
    group_id: Optional[int] = None  # null => unlink
    assignee_ids: Optional[list[int]] = None


class TaskOut(BaseModel):
    id: int
    title: str
    description: str = ""
    deadline: Optional[date] = None
    status: str
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    created_by: Optional[int] = None
    assignees: list[UserOut] = []
    assignee_ids: list[int] = []
    executors: list[UserOut] = []
    attachments: list["AttachmentOut"] = []

    class Config:
        from_attributes = True


class AttachmentOut(BaseModel):
    id: int
    task_id: int
    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0
    uploaded_by: Optional[int] = None
    url: Optional[str] = None

    class Config:
        from_attributes = True


class GroupCreate(BaseModel):
    name: str


class GroupOut(BaseModel):
    id: int
    name: str
    members: list[UserOut] = []


class MemberAdd(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None  # @username without @
