"""Persist fetched articles into the local SQLite store.

Uses SQLite's ``INSERT ... ON CONFLICT(guid) DO NOTHING`` so re-syncing a feed
silently skips entries that already exist.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from newsgator.feeds.base import FetchedArticle
from newsgator.models.article import Article
from newsgator.models.source import Source


async def store_articles(
    session: AsyncSession,
    source: Source,
    fetched: list[FetchedArticle],
) -> int:
    """Insert new articles for ``source`` and update its ``last_synced``.

    Returns the number of rows actually inserted (duplicates count as 0).
    """
    source.last_synced = datetime.now(timezone.utc)

    if not fetched:
        await session.commit()
        return 0

    rows = [{**asdict(fa), "source_id": source.id} for fa in fetched]

    before = await _count_articles_for_source(session, source.id)

    stmt = sqlite_insert(Article).values(rows).on_conflict_do_nothing(
        index_elements=["guid"]
    )
    await session.execute(stmt)
    await session.commit()

    after = await _count_articles_for_source(session, source.id)
    return after - before


async def _count_articles_for_source(session: AsyncSession, source_id: int) -> int:
    stmt = select(func.count()).select_from(Article).where(Article.source_id == source_id)
    result = await session.execute(stmt)
    return int(result.scalar_one())
