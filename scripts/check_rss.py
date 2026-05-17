"""End-to-end smoke test for the RSS provider.

Fetches a real public feed (Heise News-Ticker by default), persists into a
temporary SQLite DB, and reports how many articles were stored. Runs the sync
twice to confirm that duplicates are skipped on the second pass.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import tempfile
from pathlib import Path

import httpx
from sqlalchemy import select

from newsgator.feeds.rss import RssFeedProvider
from newsgator.models.article import Article
from newsgator.models.database import dispose_engine, get_session_factory, init_db
from newsgator.models.source import Source
from newsgator.sync.store import store_articles

DEFAULT_FEED = "https://www.heise.de/rss/heise-atom.xml"


async def run(feed_url: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "rss-smoke.db"
        await init_db(db)
        Session = get_session_factory()

        async with Session() as session:
            source = Source(url=feed_url, title=feed_url, feed_type="rss")
            session.add(source)
            await session.commit()
            await session.refresh(source)

            provider = RssFeedProvider()
            async with httpx.AsyncClient(timeout=15) as client:
                fetched = await provider.fetch(source, client)
                print(f"Fetched {len(fetched)} entries from {feed_url}")
                new_first = await store_articles(session, source, fetched)
                print(f"Stored {new_first} new articles (first pass)")

                fetched_again = await provider.fetch(source, client)
                new_second = await store_articles(session, source, fetched_again)
                print(f"Stored {new_second} new articles (second pass — should be 0)")

            stmt = (
                select(Article)
                .where(Article.source_id == source.id)
                .order_by(Article.published_at.desc().nulls_last())
                .limit(5)
            )
            rows = (await session.execute(stmt)).scalars().all()
            print("\nNewest 5 articles:")
            for a in rows:
                when = a.published_at.isoformat() if a.published_at else "—"
                print(f"  [{when}] {a.title[:80]}")

        await dispose_engine()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_FEED, help="RSS/Atom feed URL")
    args = parser.parse_args()
    asyncio.run(run(args.url))


if __name__ == "__main__":
    main()
