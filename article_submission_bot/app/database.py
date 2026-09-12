"""SQLAlchemy + SQLite persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.settings import get_settings


class Base(DeclarativeBase):
    pass


class SubmissionRecord(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_code: Mapped[str] = mapped_column(String(128), index=True)
    journal_code: Mapped[str] = mapped_column(String(128), index=True)
    package_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64), default="draft")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ConfirmationORM(Base):
    __tablename__ = "confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phrase: Mapped[str] = mapped_column(Text)
    manuscript_code: Mapped[str] = mapped_column(String(128), index=True)
    journal_name: Mapped[str] = mapped_column(String(256))
    package_hash: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    auth_file: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class AuditORM(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    manuscript_code: Mapped[str] = mapped_column(String(128), default="")
    journal_code: Mapped[str] = mapped_column(String(128), default="")
    package_hash: Mapped[str] = mapped_column(String(128), default="")
    actor: Mapped[str] = mapped_column(String(128), default="system")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str] = mapped_column(Text, default="")


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        settings.ensure_directories()
        url = settings.sqlite_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Generator[Session, None, None]:
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests(url: str = "sqlite:///:memory:") -> None:
    """Reset engine — tests only."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(_engine)
