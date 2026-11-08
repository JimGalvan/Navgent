from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.database.constants import BUSY_TIMEOUT_SECONDS


def build_engine(database_path: Path) -> Engine:
    engine = create_engine(
        URL.create("sqlite", database=str(database_path)),
        connect_args={"timeout": BUSY_TIMEOUT_SECONDS},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", enable_wal_and_foreign_keys)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def enable_wal_and_foreign_keys(connection, connection_record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()
