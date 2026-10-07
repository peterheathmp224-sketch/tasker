"""SQLAlchemy models. Rules: deadline=date only, statuses new/in_progress/done,
anyone can edit, deleting group => tasks.group_id=NULL."""
from sqlalchemy import Column, Integer, BigInteger, String, Date, ForeignKey, LargeBinary, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship, deferred
from sqlalchemy.sql import func
from .database import Base


class User(Base):
    __tablename__ = "users"
    tg_id = Column(BigInteger, primary_key=True)  # telegram id
    username = Column(String, default="", index=True)
    first_name = Column(String, default="")
    photo_url = Column(String, default="")


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    members = relationship("GroupMember", cascade="all, delete-orphan", backref="group")


class GroupMember(Base):
    __tablename__ = "group_members"
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_user"),
        Index("ix_group_members_group_user", "group_id", "user_id"),
    )


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    deadline = Column(Date, nullable=True, index=True)  # only date
    status = Column(String, default="new", index=True)  # new | in_progress | done
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(BigInteger, ForeignKey("users.tg_id"), nullable=True)
    assignees = relationship("TaskAssignee", cascade="all, delete-orphan", backref="task", lazy="selectin")
    attachments = relationship("TaskAttachment", cascade="all, delete-orphan", backref="task", lazy="selectin")
    __table_args__ = (
        Index("ix_tasks_deadline_status", "deadline", "status"),
        Index("ix_tasks_group_deadline", "group_id", "deadline"),
    )


class TaskAssignee(Base):
    __tablename__ = "task_assignees"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_user"),
        Index("ix_task_assignees_task_user", "task_id", "user_id"),
        Index("ix_task_assignees_user_task", "user_id", "task_id"),
    )


class TaskAttachment(Base):
    """Файл, прикреплённый к задаче. Байты хранятся прямо в БД (BYTEA)."""
    __tablename__ = "task_attachments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, default="application/octet-stream")
    size = Column(Integer, nullable=False, default=0)
    # BYTEA: тяжёлое поле — грузим только при скачивании (download_attachment),
    # в списках читаем только метаданные через load_only/defer.
    data = deferred(Column(LargeBinary, nullable=False))
    uploaded_by = Column(BigInteger, ForeignKey("users.tg_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
