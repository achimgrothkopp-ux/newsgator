"""End-to-end smoke test for the HTTP-Scraper provider.

Fetches a single article URL, runs trafilatura over it, persists, and reports
title / date / excerpt. Re-runs the sync to confirm deduplication.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import tempfile
from pathlib import Path

import httpx

from newsgator.feeds.http import HttpFeedProvider
from newsgator.models.database import dispose_engine, get_session_factory, init_db
from newsgator.models.source import Source
from newsgator.sync.store import store_articles

DEFAULT_URL = "https://docs.astral.sh/uv/getting-started/installation/"


async def run(url: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "http-smoke.db"
        await init_db(db)
        Session = get_session_factory()

        async with Session() as session:
            source = Source(url=url, title=url, feed_type="http")
            session.add(source)
            await session.commit()
            await session.refresh(source)

            provider = HttpFeedProvider()
            async with httpx.AsyncClient(timeout=15) as client:
                fetched = await provider.fetch(source, client)
                print(f"Fetched {len(fetched)} article(s) from {url}")
                new_first = await store_articles(session, source, fetched)
                print(f"Stored {new_first} new article(s) (first pass)")

                fetched_again = await provider.fetch(source, client)
                new_second = await store_articles(session, source, fetched_again)
                print(f"Stored {new_second} new article(s) (second pass — should be 0)")

            if fetched:
                a = fetched[0]
                print("\nExtracted article:")
                print(f"  title:        {a.title}")
                print(f"  published_at: {a.published_at}")
                print(f"  summary:      {a.summary}")
                print(f"  content_len:  {len(a.content or '')} chars")

        await dispose_engine()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Article URL to scrape")
    args = parser.parse_args()
    asyncio.run(run(args.url))


if __name__ == "__main__":
    main()
