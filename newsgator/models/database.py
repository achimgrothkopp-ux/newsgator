"""Async SQLAlchemy engine and session factory for the local SQLite store."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _default_db_path() -> Path:
    """Return the default on-disk location for the SQLite database.

    Follows the XDG Base Directory spec on Linux:
    ``$XDG_DATA_HOME/newsgator/newsgator.db`` (falls back to ``~/.local/share``).
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "newsgator" / "newsgator.db"


def get_engine(db_path: Path | str | None = None, *, echo: bool = False) -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    if db_path is None:
        db_path = _default_db_path()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = f"sqlite+aiosqlite:///{db_path}"
    _engine = create_async_engine(url, echo=echo, future=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory bound to the engine (initialising if needed)."""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


async def init_db(db_path: Path | str | None = None) -> None:
    """Create all tables. Safe to call repeatedly."""
    # Import models so their tables are registered on Base.metadata.
    from newsgator.models import article, source  # noqa: F401

    engine = get_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Close the engine and reset module-level state (mainly for tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
