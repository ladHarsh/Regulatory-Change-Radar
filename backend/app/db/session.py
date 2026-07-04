"""
db/session.py — SQLAlchemy session factory and FastAPI dependency.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base


def _get_engine():
    """Creates the SQLAlchemy engine. SQLite WAL mode is enabled for better concurrency."""
    settings = get_settings()
    engine = create_engine(
        settings.sqlite_url,
        connect_args={"check_same_thread": False},  # Required for SQLite with FastAPI
        echo=(settings.app_env == "development"),    # Log SQL in dev mode
    )

    # Enable WAL mode for SQLite — better read concurrency
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = _get_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def init_db() -> None:
    """
    Creates all tables if they don't exist.
    Called once at application startup.
    """
    import os
    from app.config import get_settings
    settings = get_settings()
    os.makedirs(settings.data_dir, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session.
    Ensures the session is always closed, even on exceptions.

    Usage:
        @app.get("/...")
        def my_endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager version for use outside FastAPI dependency injection
    (e.g., background tasks, CLI scripts).
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
