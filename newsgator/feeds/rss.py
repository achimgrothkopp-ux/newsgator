"""RSS/Atom feed provider using feedparser."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from time import struct_time
from typing import Any, ClassVar

import feedparser
import httpx

from newsgator.feeds.base import FeedProvider, FetchedArticle
from newsgator.models.source import Source

logger = logging.getLogger(__name__)

USER_AGENT = "newsgator/0.1 (+https://github.com/achimgrothkopp-ux/newsgator)"


class RssFeedProvider(FeedProvider):
    feed_type: ClassVar[str] = "rss"

    async def fetch(
        self, source: Source, client: httpx.AsyncClient
    ) -> list[FetchedArticle]:
        return await self._fetch_from_url(source.url, client)

    async def _fetch_from_url(
        self, url: str, client: httpx.AsyncClient
    ) -> list[FetchedArticle]:
        """Shared helper: fetch the feed at ``url`` and parse it.

        Split from ``fetch`` so subclasses (e.g. YoutubeFeedProvider) can
        resolve their own URL before delegating, without having to mutate
        the Source object.
        """
        try:
            response = await client.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
                },
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("RSS fetch failed for %s: %s", url, exc)
            return []

        # feedparser.parse() is synchronous and CPU-bound on large feeds —
        # keep the qasync event loop responsive by running it in a thread.
        parsed = await asyncio.to_thread(feedparser.parse, response.content)

        if parsed.bozo and not parsed.entries:
            logger.warning(
                "RSS feed %s could not be parsed: %s",
                url,
                getattr(parsed, "bozo_exception", "unknown error"),
            )
            return []

        return [self._entry_to_article(entry, url) for entry in parsed.entries]

    @staticmethod
    def _entry_to_article(entry: Any, source_url: str) -> FetchedArticle:
        link = (entry.get("link") or "").strip()
        title = (entry.get("title") or "(ohne Titel)").strip()
        guid = _pick_guid(entry, source_url, link, title)

        published_at = _parse_struct_time(
            entry.get("published_parsed") or entry.get("updated_parsed")
        )

        summary = entry.get("summary") or None
        content = None
        contents = entry.get("content")
        if contents:
            # entry.content is a list of dicts ({type, language, value})
            content = "\n".join(c.get("value", "") for c in contents) or None

        return FetchedArticle(
            guid=guid,
            title=title,
            url=link,
            published_at=published_at,
            summary=summary,
            content=content,
        )


def _pick_guid(entry: Any, source_url: str, link: str, title: str) -> str:
    """Stable identifier for deduplication.

    Order: explicit feed-level id → link → sha1 of (source_url + title).
    """
    candidate = (entry.get("id") or entry.get("guid") or "").strip()
    if candidate:
        return candidate
    if link:
        return link
    digest = hashlib.sha1(f"{source_url}|{title}".encode("utf-8")).hexdigest()
    return f"sha1:{digest}"


def _parse_struct_time(value: struct_time | None) -> datetime | None:
    if not value:
        return None
    try:
        # struct_time from feedparser is UTC. Build a tz-aware datetime.
        return datetime(*value[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
