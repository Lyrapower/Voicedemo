from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings


def _connect_args() -> dict:
    u = (settings.database_url or "").lower()
    if u.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _pool_kw() -> dict:
    u = (settings.database_url or "").lower()
    if u.startswith("sqlite"):
        return {}
    return {"pool_pre_ping": True}


engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(),
    **_pool_kw(),
)

# Enforce foreign keys in SQLite
if settings.database_url.lower().startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_fk(dbapi_connection, _rec):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
