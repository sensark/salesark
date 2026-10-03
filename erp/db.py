from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from alembic import command
from alembic.config import Config

from erp import config

_url = make_url(config.DATABASE_URL)
_engine_options: dict = {}
if not _url.drivername.startswith("sqlite"):
    connect_args: dict = {"connect_timeout": 15, "read_timeout": 60, "write_timeout": 60}
    # PyMySQL rejects the MySQL-client "ssl-mode" query option (used by Aiven etc.); map it to ssl args.
    ssl_mode = (_url.query.get("ssl-mode") or _url.query.get("ssl_mode") or "").upper()
    _url = _url.difference_update_query(["ssl-mode", "ssl_mode"])
    if ssl_mode and ssl_mode != "DISABLED":
        connect_args["ssl"] = {"check_hostname": ssl_mode == "VERIFY_IDENTITY"}
    _engine_options = {
        # The remote server drops connections (sometimes silently); validate, recycle and time out.
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "connect_args": connect_args,
    }
engine = create_engine(_url, future=True, **_engine_options)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if config.DATABASE_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
_migration_lock = Lock()


def init_db() -> None:
    root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(root / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url).replace("%", "%%"))
    with _migration_lock:
        command.upgrade(alembic_cfg, "head")


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
