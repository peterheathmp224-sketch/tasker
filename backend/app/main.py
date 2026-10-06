from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import os
from .database import engine, Base
from . import models  # noqa: F401 (register tables)
from .schemas import AuthIn
from .deps import get_current_user
from .routers import users, tasks, groups, calendar

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Tasker Mini App")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(groups.router)
app.include_router(calendar.router)


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
APP_VERSION = "8"
NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate"}
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web")
if os.path.isdir(WEB_DIR):
    @app.get("/", include_in_schema=False)
    def _index():
        with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
            html = f.read()
        html = html.replace("/app.js", "/app.js?v=" + APP_VERSION).replace("/styles.css", "/styles.css?v=" + APP_VERSION)
        return Response(html, media_type="text/html", headers=NO_STORE)

    @app.get("/app.js", include_in_schema=False)
    def _js():
        return FileResponse(os.path.join(WEB_DIR, "app.js"), media_type="application/javascript", headers=NO_STORE)

    @app.get("/styles.css", include_in_schema=False)
    def _css():
        return FileResponse(os.path.join(WEB_DIR, "styles.css"), media_type="text/css", headers=NO_STORE)
