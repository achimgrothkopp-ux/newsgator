"""ORM model for articles fetched from any source."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsgator.models.database import Base

if TYPE_CHECKING:
    from newsgator.models.source import Source


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )

    # GUID from the feed (or a hash of the URL for sources without one).
    # UNIQUE so re-syncs can use INSERT OR IGNORE to skip duplicates.
    guid: Mapped[str] = mapped_column(String, unique=True, index=True)

    title: Mapped[str]
    url: Mapped[str]
    published_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    summary: Mapped[str | None] = mapped_column(Text, default=None)
    content: Mapped[str | None] = mapped_column(Text, default=None)

    is_read: Mapped[bool] = mapped_column(default=False, index=True)
    is_archived: Mapped[bool] = mapped_column(default=False, index=True)
    archived_html: Mapped[str | None] = mapped_column(Text, default=None)

    source: Mapped["Source"] = relationship(back_populates="articles")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Article id={self.id} title={self.title!r}>"
