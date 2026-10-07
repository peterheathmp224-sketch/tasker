from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import os
from .database import engine, Base
from . import models  # noqa: F401 (register tables)
from .schemas import AuthIn
from .deps import get_current_user
from .routers import users, tasks, groups, calendar, auth

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    raise RuntimeError(
        "Cannot initialize Postgres on startup. Check DATABASE_URL in backend/.env "
        "(plain ASCII, no Cyrillic/invisible chars, file saved as UTF-8) "
        "and that Postgres is running (docker compose up -d db)."
    ) from e

# Индексы для уже существующих БД (create_all их не добавит задним числом).
# IF NOT EXISTS — безопасно выполнять на каждом старте.
_EXTRA_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_tasks_deadline ON tasks (deadline)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_group_id ON tasks (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_deadline_status ON tasks (deadline, status)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_group_deadline ON tasks (group_id, deadline)",
    "CREATE INDEX IF NOT EXISTS ix_task_assignees_task_user ON task_assignees (task_id, user_id)",
    "CREATE INDEX IF NOT EXISTS ix_task_assignees_user_task ON task_assignees (user_id, task_id)",
    "CREATE INDEX IF NOT EXISTS ix_group_members_group_user ON group_members (group_id, user_id)",
    "CREATE INDEX IF NOT EXISTS ix_task_attachments_task_id ON task_attachments (task_id)",
    "CREATE INDEX IF NOT EXISTS ix_users_username ON users (username)",
)
try:
    from sqlalchemy import text as _text

    with engine.connect() as _conn:
        for _ddl in _EXTRA_INDEXES:
            _conn.execute(_text(_ddl))
        _conn.commit()
except Exception:
    # Не блокируем старт приложения, если у пользователя нет прав на DDL.
    pass

app = FastAPI(title="Tasker Mini App")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(groups.router)
app.include_router(calendar.router)
app.include_router(auth.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/auth/telegram")
def auth(_: AuthIn, user: models.User = Depends(get_current_user)):
    # get_current_user already validates initData + upserts user
    return {"tg_id": user.tg_id, "username": user.username, "first_name": user.first_name, "photo_url": user.photo_url}


# ---- static Mini App (no node build) ----
# APP_VERSION bump on every web/ change — cache-buster for Telegram WebView,
# which aggressively caches /app.js (stale JS = stale API queries).
APP_VERSION = "12"
NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate"}
# Версионированные ассеты (?v=) иммутабельны — браузер/ WebView кэширует год,
# index.html всегда свежий (no-store), чтобы подхватить новую версию.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web")
_INDEX_TEMPLATE = ""
if os.path.isdir(WEB_DIR):
    try:
        with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as _f:
            _INDEX_TEMPLATE = _f.read()
    except OSError:
        _INDEX_TEMPLATE = ""
if os.path.isdir(WEB_DIR):
    @app.get("/", include_in_schema=False)
    def _index():
        # Без чтения с диска на каждый запрос: шаблон загружен один раз на старте.
        html = _INDEX_TEMPLATE.replace("/app.js", "/app.js?v=" + APP_VERSION).replace("/styles.css", "/styles.css?v=" + APP_VERSION)
        return Response(html, media_type="text/html", headers=NO_STORE)

    @app.get("/app.js", include_in_schema=False)
    def _js():
        return FileResponse(os.path.join(WEB_DIR, "app.js"), media_type="application/javascript", headers=IMMUTABLE)

    @app.get("/styles.css", include_in_schema=False)
    def _css():
        return FileResponse(os.path.join(WEB_DIR, "styles.css"), media_type="text/css", headers=IMMUTABLE)
