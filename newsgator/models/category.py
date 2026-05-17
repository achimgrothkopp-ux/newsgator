"""ORM model for the categories registry.

Categories also live as a plain string column on ``Source`` — that column
is the source of truth for "what category is this feed in." The
``categories`` table merely persists categories the user has *declared*
(via the Categories dialog or the "+" button in AddSource) so they remain
available in dropdowns even when no source uses them yet.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from newsgator.models.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Category id={self.id} name={self.name!r}>"
