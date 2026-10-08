"""SQLAlchemy 引擎与会话。使用 SQLite 默认配置，开箱即用；换 Postgres 只改 DATABASE_URL。"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    future=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 引擎钩子
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=8000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """统一 declarative base。"""


def ensure_dirs() -> None:
    for p in (
        Path(settings.export_dir),
        Path(settings.asset_dir),
        Path(settings.plugin_dir),
    ):
        p.mkdir(parents=True, exist_ok=True)
    if _is_sqlite:
        # sqlite:///... -> data/campaign_edit.db
        raw = settings.database_url.split("sqlite:///", 1)[-1]
        if raw and raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册

    ensure_dirs()
    Base.metadata.create_all(bind=engine)