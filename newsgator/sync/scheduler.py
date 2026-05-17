"""Periodic background sync over all sources.

Design notes
------------
* Provider instances are stateless and shared.
* Each source gets its own ``AsyncSession`` so a failure (or a slow commit)
  on one source can't poison the others. SQLAlchemy's AsyncSession is not
  safe to share across concurrent tasks.
* ``sync_all()`` is the unit of work. ``start()/stop()`` just runs it on a
  timer; manual "Refresh" buttons in the UI can call ``sync_all()`` directly.
* Errors are logged, never raised — a flaky feed must not stop the loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.feeds.base import FeedProvider
from newsgator.feeds.http import HttpFeedProvider
from newsgator.feeds.rss import RssFeedProvider
from newsgator.feeds.youtube import YoutubeFeedProvider
from newsgator.models.source import Source
from newsgator.sync.store import store_articles

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, FeedProvider] = {
    RssFeedProvider.feed_type: RssFeedProvider(),
    HttpFeedProvider.feed_type: HttpFeedProvider(),
    YoutubeFeedProvider.feed_type: YoutubeFeedProvider(),
}

DEFAULT_INTERVAL_MINUTES = 15
DEFAULT_HTTP_TIMEOUT = 15.0


@dataclass(slots=True)
class SourceSyncResult:
    source_id: int
    source_url: str
    feed_type: str
    new_articles: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class FeedScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
        on_sync_complete: Callable[[list[SourceSyncResult]], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._interval = max(1.0, interval_minutes) * 60
        self._http_timeout = http_timeout
        self._task: asyncio.Task[None] | None = None
        # Fired after every background sync_all (not on manual UI-triggered
        # sync_all — those handle their own UI updates).
        self._on_sync_complete = on_sync_complete

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="newsgator-sync-loop")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                results = await self.sync_all()
            except Exception:  # pragma: no cover - safety net
                logger.exception("sync_all crashed; will retry next tick")
            else:
                if self._on_sync_complete is not None:
                    try:
                        self._on_sync_complete(results)
                    except Exception:  # pragma: no cover - never let UI bugs break the loop
                        logger.exception("on_sync_complete callback raised")
            await asyncio.sleep(self._interval)

    async def sync_all(self) -> list[SourceSyncResult]:
        async with self._session_factory() as session:
            sources = (await session.execute(select(Source))).scalars().all()

        if not sources:
            logger.info("sync_all: no sources configured")
            return []

        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
            tasks = [self._sync_one(src, client) for src in sources]
            results = await asyncio.gather(*tasks, return_exceptions=False)

        logger.info(
            "sync_all done: %d sources, %d new articles, %d errors",
            len(results),
            sum(r.new_articles for r in results),
            sum(1 for r in results if r.error),
        )
        return results

    async def _sync_one(
        self, source: Source, client: httpx.AsyncClient
    ) -> SourceSyncResult:
        provider = PROVIDERS.get(source.feed_type)
        if provider is None:
            msg = f"unknown feed_type {source.feed_type!r}"
            logger.warning("source #%s: %s", source.id, msg)
            return SourceSyncResult(source.id, source.url, source.feed_type, 0, msg)

        try:
            fetched = await provider.fetch(source, client)
        except Exception as exc:  # provider should swallow HTTP errors itself,
            # but anything else (parser bug, network at a weird layer) still
            # belongs in the per-source error bucket — not on the loop.
            logger.warning(
                "source #%s (%s) provider raised: %s",
                source.id,
                source.url,
                exc,
            )
            return SourceSyncResult(
                source.id, source.url, source.feed_type, 0, str(exc)
            )

        try:
            async with self._session_factory() as session:
                merged = await session.merge(source)
                new_count = await store_articles(session, merged, fetched)
        except Exception as exc:
            logger.warning(
                "source #%s (%s) persist failed: %s",
                source.id,
                source.url,
                exc,
            )
            return SourceSyncResult(
                source.id, source.url, source.feed_type, 0, str(exc)
            )

        return SourceSyncResult(source.id, source.url, source.feed_type, new_count)
