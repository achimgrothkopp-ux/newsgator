"""End-to-end smoke test for FeedScheduler.

Sets up four sources (one of each provider type plus a deliberately broken
URL), runs sync_all() once, and prints the per-source result so we can see
that errors are isolated and good sources still get persisted.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from newsgator.models.database import dispose_engine, get_session_factory, init_db
from newsgator.models.source import Source
from newsgator.sync.scheduler import FeedScheduler

SOURCES: list[tuple[str, str, str]] = [
    ("rss",     "Heise News",       "https://www.heise.de/rss/heise-atom.xml"),
    ("http",    "uv docs",          "https://docs.astral.sh/uv/getting-started/installation/"),
    ("youtube", "Veritasium",       "https://www.youtube.com/@veritasium"),
    ("rss",     "broken (DNS)",     "https://this-host-does-not-exist.invalid/feed.xml"),
]


async def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "scheduler-smoke.db"
        await init_db(db)
        Session = get_session_factory()

        async with Session() as session:
            for feed_type, title, url in SOURCES:
                session.add(Source(url=url, title=title, feed_type=feed_type))
            await session.commit()

        scheduler = FeedScheduler(Session, interval_minutes=15)
        results = await scheduler.sync_all()

        print("\nPer-source results:")
        print(f"  {'#':>2}  {'type':<8} {'new':>5}  {'status':<8}  url")
        print(f"  {'-'*2:>2}  {'-'*8:<8} {'-'*5:>5}  {'-'*8:<8}  {'-'*60}")
        for r in results:
            status = "ok" if r.ok else "ERROR"
            note = f" — {r.error}" if r.error else ""
            print(f"  {r.source_id:>2}  {r.feed_type:<8} {r.new_articles:>5}  {status:<8}  {r.source_url}{note}")

        total_new = sum(r.new_articles for r in results)
        ok_count = sum(1 for r in results if r.ok)
        print(f"\nTotal: {ok_count}/{len(results)} sources ok, {total_new} new articles")

        await dispose_engine()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
