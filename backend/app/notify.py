"""Best-effort уведомления о событиях задач/групп через Telegram Bot API.

- Только stdlib (urllib), без новых зависимостей.
- Никогда не роняет API: вызывается из FastAPI BackgroundTasks
  с готовыми plain-данными (без DB-сессии, она к тому моменту закрыта).
- Тихо пропускаем: нет BOT_TOKEN, 403 (юзер заблокировал бота),
  400 (chat not found — юзер ни разу не запускал бота).
"""
import html
import json
import logging
import os
import urllib.error
import urllib.request
from sqlalchemy.orm import Session
from . import models

log = logging.getLogger("tasker.notify")

STATUS_RU = {"new": "Новая", "in_progress": "В работе", "done": "Готово"}


def _token() -> str:
    t = os.getenv("BOT_TOKEN", "")
    if not t or "PUT-YOUR-TOKEN" in t:
        return ""
    return t


def _footer() -> str:
    url = os.getenv("WEBAPP_URL", "").rstrip("/")
    return f'\n\n<a href="{html.escape(url)}">Открыть Tasker</a>' if url else ""


def send_message(chat_id: int, text: str, timeout: float = 10.0) -> bool:
    """Отправить одно сообщение. True — доставлено, False — пропуск/ошибка."""
    token = _token()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
        return body.get("ok") is True
    except urllib.error.HTTPError as e:
        # 403 — бот заблокирован юзером, 400 — чата нет (бот не запускался).
        # Оба случая штатные: просто не отправляем.
        if e.code in (400, 403):
            return False
        try:
            detail = e.read().decode()[:200]
        except Exception:
            detail = ""
        log.warning("telegram sendMessage chat_id=%s http=%s %s", chat_id, e.code, detail)
        return False
    except Exception as e:
        log.warning("telegram sendMessage chat_id=%s failed: %r", chat_id, e)
        return False


def broadcast(chat_ids, text: str) -> int:
    """Разослать нескольким получателям (с дедупликацией). Возвращает число доставок."""
    sent = 0
    for cid in dict.fromkeys(chat_ids):
        if cid and send_message(cid, text):
            sent += 1
    return sent


# ---------- helpers: plain-данные для фоновых задач ----------

def actor_out(user: models.User) -> dict:
    return {
        "tg_id": user.tg_id,
        "username": user.username or "",
        "first_name": user.first_name or "",
    }


def group_name(db: Session, gid: int | None) -> str | None:
    if not gid:
        return None
    g = db.get(models.Group, gid)
    return g.name if g else None


def group_members(db: Session, gid: int | None) -> set[int]:
    if not gid:
        return set()
    return {r[0] for r in db.query(models.GroupMember.user_id).filter_by(group_id=gid).all()}


def task_participants(db: Session, task_id: int, group_id: int | None, created_by: int | None) -> set[int]:
    """Прямые исполнители + участники группы + создатель."""
    ids = {r[0] for r in db.query(models.TaskAssignee.user_id).filter_by(task_id=task_id).all()}
    ids.update(group_members(db, group_id))
    if created_by:
        ids.add(created_by)
    return ids


def _who(actor: dict) -> str:
    un = (actor.get("username") or "").strip().lstrip("@")
    fn = (actor.get("first_name") or "").strip()
    if un and fn:
        return f"@{un} ({fn})"
    if un:
        return f"@{un}"
    return fn or f"id{actor.get('tg_id')}"


def _ctx(deadline=None, group: str | None = None) -> list[str]:
    lines = []
    if deadline:
        lines.append(f"📅 {deadline}")
    if group:
        lines.append(f"👥 {group}")
    return lines


def _fmt_size(n: int) -> str:
    n = int(n or 0)
    if n < 1024:
        return f"{n} Б"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} КБ"
    return f"{n / 1024 / 1024:.1f} МБ"


def _msg(lines: list[str]) -> str:
    # Весь пользовательский контент экранируем (parse_mode=HTML);
    # своих тегов в строках нет — только текст и эмодзи.
    return "\n".join(html.escape(x) for x in lines if x) + _footer()


# ---------- тексты событий ----------

def task_created(task: dict, actor: dict) -> str:
    return _msg([
        "📌 Новая задача",
        f"«{task['title']}»",
        *_ctx(task.get("deadline"), task.get("group_name")),
        f"👤 Поставил: {_who(actor)}",
    ])


def task_status(task: dict, actor: dict, old: str, new: str) -> str:
    title = f"«{task['title']}»"
    if new == "done":
        head = f"✅ Задача {title} выполнена"
    elif new == "in_progress" and old == "new":
        head = f"▶️ {title} взята в работу"
    elif old == "done":
        head = f"↩️ Задача {title} переоткрыта"
    else:
        head = f"🔄 Задача {title}: {STATUS_RU.get(old, old)} → {STATUS_RU.get(new, new)}"
    return _msg([head, *_ctx(task.get("deadline"), task.get("group_name")), f"👤 {_who(actor)}"])


def task_assignee_added(task: dict, actor: dict) -> str:
    return _msg([
        "📌 Вас назначили на задачу",
        f"«{task['title']}»",
        *_ctx(task.get("deadline"), task.get("group_name")),
        f"👤 {_who(actor)}",
    ])


def task_assignee_removed(task: dict, actor: dict) -> str:
    return _msg([f"Вас сняли с задачи «{task['title']}»", f"👤 {_who(actor)}"])


def task_group_attached(task: dict, actor: dict, group: str) -> str:
    return _msg([f"Задача «{task['title']}» прикреплена к группе «{group}»", f"👤 {_who(actor)}"])


def task_group_detached(task: dict, actor: dict, group: str) -> str:
    return _msg([f"Задача «{task['title']}» откреплена от группы «{group}»", f"👤 {_who(actor)}"])


def task_deadline_changed(task: dict, actor: dict, old, new) -> str:
    return _msg([
        f"⏰ У задачи «{task['title']}» новый срок: {new or 'без срока'} (был {old or 'без срока'})",
        f"👤 {_who(actor)}",
    ])


def task_deleted(title: str, deadline, actor: dict) -> str:
    lines = [f"🗑 Задача «{title}» удалена"]
    if deadline:
        lines.append(f"📅 {deadline}")
    lines.append(f"👤 {_who(actor)}")
    return _msg(lines)


def group_deleted(name: str, actor: dict) -> str:
    return _msg([f"👥 Группа «{name}» удалена, задачи отвязаны", f"👤 {_who(actor)}"])


def group_member_added(name: str, actor: dict) -> str:
    return _msg([f"👥 Вас добавили в группу «{name}»", f"👤 {_who(actor)}"])


def group_member_removed(name: str, actor: dict) -> str:
    return _msg([f"Вас убрали из группы «{name}»", f"👤 {_who(actor)}"])


def file_uploaded(task: dict, actor: dict, filename: str, size: int) -> str:
    return _msg([
        f"📎 {_who(actor)} прикрепил файл «{filename}» ({_fmt_size(size)})",
        f"к задаче «{task['title']}»",
    ])
