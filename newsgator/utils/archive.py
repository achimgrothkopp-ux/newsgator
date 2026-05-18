"""Archive an article for offline reading.

Re-fetches ``article.url`` and runs trafilatura with HTML output so the body
keeps its paragraphs/lists/headings. The extracted HTML lands in
``Article.archived_html``; the view layer wraps it with the current theme on
demand, so theme switches still affect archived articles.

Network errors and empty extractions are returned as ``ArchiveResult(ok=False,
…)`` instead of raised — callers (UI menu actions) want to surface a friendly
error in the status bar, not crash the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx
import trafilatura
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.article import Article

logger = logging.getLogger(__name__)

USER_AGENT = "newsgator/0.1 (+https://github.com/achimgrothkopp-ux/newsgator)"
FETCH_TIMEOUT = 20.0


@dataclass(slots=True, frozen=True)
class ArchiveResult:
    ok: bool
    error: str | None = None


async def archive_article(
    article_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> ArchiveResult:
    async with session_factory() as session:
        article = await session.get(Article, article_id)
        if article is None:
            return ArchiveResult(ok=False, error="Artikel nicht gefunden")
        if not article.url:
            return ArchiveResult(ok=False, error="Artikel hat keine URL")
        url = article.url

    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("archive: fetch failed for %s: %s", url, exc)
        return ArchiveResult(ok=False, error=f"Download fehlgeschlagen: {exc}")

    html_body = await asyncio.to_thread(_extract_html, response.text, url)
    if not html_body:
        return ArchiveResult(ok=False, error="Kein Inhalt extrahiert")

    async with session_factory() as session:
        article = await session.get(Article, article_id)
        if article is None:
            return ArchiveResult(ok=False, error="Artikel verschwand während des Archivierens")
        article.archived_html = html_body
        article.is_archived = True
        await session.commit()

    logger.info("archive: stored %d chars for article #%d", len(html_body), article_id)
    return ArchiveResult(ok=True)


async def unarchive_article(
    article_id: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> ArchiveResult:
    async with session_factory() as session:
        article = await session.get(Article, article_id)
        if article is None:
            return ArchiveResult(ok=False, error="Artikel nicht gefunden")
        article.is_archived = False
        article.archived_html = None
        await session.commit()
    logger.info("archive: removed article #%d from archive", article_id)
    return ArchiveResult(ok=True)


def _extract_html(html: str, url: str) -> str | None:
    """Run trafilatura with HTML output in a worker thread."""
    extracted = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        favor_recall=True,
        include_comments=False,
        include_tables=True,
        include_images=True,
        include_links=True,
    )
    if not extracted:
        logger.warning("archive: trafilatura returned no content for %s", url)
        return None
    return extracted
