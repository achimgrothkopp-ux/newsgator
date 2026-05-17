"""End-to-end smoke test for the YouTube provider.

Tries multiple input URL formats (handle, /channel/UC..., direct RSS) so we
can see the resolver work, then persists the entries and runs a dedup pass.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import httpx

from newsgator.feeds.youtube import YoutubeFeedProvider
from newsgator.models.database import dispose_engine, get_session_factory, init_db
from newsgator.models.source import Source
from newsgator.sync.store import store_articles

# Veritasium — picked because the channel is huge and stable across all three
# URL forms; if YouTube ever breaks one of these patterns, the test will tell.
CHANNELS = [
    "https://www.youtube.com/@veritasium",
    "https://www.youtube.com/channel/UCHnyfMqiRRG1u-2MsSQLbXA",
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCHnyfMqiRRG1u-2MsSQLbXA",
]


async def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "youtube-smoke.db"
        await init_db(db)
        Session = get_session_factory()

        provider = YoutubeFeedProvider()
        async with httpx.AsyncClient(timeout=20) as client:
            for i, url in enumerate(CHANNELS, 1):
                async with Session() as session:
                    source = Source(url=url, title=url, feed_type="youtube")
                    session.add(source)
                    await session.commit()
                    await session.refresh(source)

                    fetched = await provider.fetch(source, client)
                    new_count = await store_articles(session, source, fetched)
                    print(f"[{i}] {url}")
                    print(f"    fetched={len(fetched)}, stored={new_count}")
                    if fetched:
                        a = fetched[0]
                        published = a.published_at.isoformat() if a.published_at else "—"
                        print(f"    latest: [{published}] {a.title}")
                        print(f"            {a.url}")

            print("\nDedup check on first channel:")
            async with Session() as session:
                first = await session.get(Source, 1)
                assert first is not None
                fetched_again = await provider.fetch(first, client)
                new_count = await store_articles(session, first, fetched_again)
                print(f"    second pass: stored={new_count} (should be 0)")

        await dispose_engine()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
