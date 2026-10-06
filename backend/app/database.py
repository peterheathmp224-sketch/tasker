import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()
# Postgres, e.g. postgresql+psycopg2://tasker:tasker@localhost:5432/tasker
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://tasker:tasker@localhost:5432/tasker")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
