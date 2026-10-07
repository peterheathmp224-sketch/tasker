import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Явный путь к backend/.env (не зависит от cwd, откуда запустили uvicorn)
# и строго UTF-8: файл с другой кодировкой упадёт здесь с понятной ошибкой,
# а не потом с UnicodeDecodeError внутри psycopg2.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
try:
    load_dotenv(dotenv_path=_ENV_PATH, encoding="utf-8")
except UnicodeDecodeError as e:
    raise RuntimeError(
        f"backend/.env is not valid UTF-8 ({e}). "
        "Re-save backend/.env as UTF-8 without BOM."
    ) from e
# Postgres, e.g. postgresql+psycopg2://tasker:tasker@localhost:5432/tasker
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://tasker:tasker@localhost:5432/tasker")

# Fail fast: не-ASCII в URL (кириллица вместо латиницы, невидимые символы
# из копипасты) иначе упадёт глубоко внутри psycopg2 с cryptic UnicodeDecodeError.
_bad = [(i, hex(ord(c))) for i, c in enumerate(DATABASE_URL) if ord(c) > 127]
if _bad:
    raise RuntimeError(
        f"DATABASE_URL contains non-ASCII characters at positions {_bad}. "
        "Retype the DATABASE_URL line in backend/.env in plain ASCII (UTF-8)."
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_recycle=300,
)
# expire_on_commit=False: после commit атрибуты не протухают,
# не нужен лишний SELECT (refresh) чтобы прочитать id только что созданной строки.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
