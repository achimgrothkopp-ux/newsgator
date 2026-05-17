"""Abstract base for all feed providers (RSS, HTTP, YouTube)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

import httpx

from newsgator.models.source import Source


@dataclass(slots=True)
class FetchedArticle:
    """One article as returned by a provider — DB-agnostic.

    Persistence (insert-or-ignore on guid, FK to source, last_synced bookkeeping)
    is the caller's job.
    """

    guid: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str | None = None
    content: str | None = None


class FeedProvider(ABC):
    """A provider knows how to turn a Source into a list of FetchedArticle."""

    feed_type: ClassVar[str]

    @abstractmethod
    async def fetch(
        self, source: Source, client: httpx.AsyncClient
    ) -> list[FetchedArticle]:
        """Fetch and parse the source. Should not raise for HTTP errors —
        callers want to log a warning and move on, not crash the whole sync.
        """
        raise NotImplementedError
