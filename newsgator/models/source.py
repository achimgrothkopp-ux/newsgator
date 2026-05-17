"""ORM model for feed sources (RSS, HTTP, YouTube)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsgator.models.database import Base

if TYPE_CHECKING:
    from newsgator.models.article import Article


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String, unique=True, index=True)
    title: Mapped[str]
    feed_type: Mapped[str] = mapped_column(String(16))  # "rss" | "http" | "youtube"
    category: Mapped[str | None] = mapped_column(default=None, index=True)
    favicon_path: Mapped[str | None] = mapped_column(default=None)
    last_synced: Mapped[datetime | None] = mapped_column(default=None)

    articles: Mapped[list["Article"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Source id={self.id} type={self.feed_type!r} url={self.url!r}>"
