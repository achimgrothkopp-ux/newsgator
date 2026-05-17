"""HTTP scraper provider: extracts the main article from a single page.

Treats one Source URL as one article — sync-runs are deduplicated on the URL,
so re-syncing a page that hasn't changed produces 0 new rows. If the page
content changes, the dedup still kicks in (same URL == same guid); to track
updates as new entries we'd hash the content instead, but that creates
spurious duplicates for cosmetic page changes and is left out of v0.1.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import ClassVar

import httpx
import trafilatura
from trafilatura.metadata import extract_metadata

from newsgator.feeds.base import FeedProvider, FetchedArticle
from newsgator.models.source import Source

logger = logging.getLogger(__name__)

USER_AGENT = "newsgator/0.1 (+https://github.com/achimgrothkopp-ux/newsgator)"
SUMMARY_LEN = 300


class HttpFeedProvider(FeedProvider):
    feed_type: ClassVar[str] = "http"

    async def fetch(
        self, source: Source, client: httpx.AsyncClient
    ) -> list[FetchedArticle]:
        try:
            response = await client.get(
                source.url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("HTTP fetch failed for %s: %s", source.url, exc)
            return []

        html = response.text
        article = await asyncio.to_thread(_extract_article, html, source.url)
        return [article] if article else []


def _extract_article(html: str, url: str) -> FetchedArticle | None:
    """Run the synchronous trafilatura extraction in a worker thread."""
    content = trafilatura.extract(
        html,
        url=url,
        favor_recall=True,
        include_comments=False,
        include_tables=False,
    )
    if not content:
        logger.warning("trafilatura returned no content for %s", url)
        return None

    title = url
    published_at: datetime | None = None
    metadata = extract_metadata(html, default_url=url)
    if metadata:
        title = (metadata.title or url).strip()
        published_at = _parse_iso_date(metadata.date)

    summary = content[:SUMMARY_LEN].rsplit(" ", 1)[0] + ("…" if len(content) > SUMMARY_LEN else "")

    return FetchedArticle(
        guid=f"http:{url}",
        title=title,
        url=url,
        published_at=published_at,
        summary=summary,
        content=content,
    )


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # trafilatura returns dates like "2024-03-15" or full ISO timestamps.
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
