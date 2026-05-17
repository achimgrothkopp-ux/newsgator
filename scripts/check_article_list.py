"""Headless smoke test for the article list.

Seeds two sources in different categories, three articles each (mixed
read/unread), then walks every sidebar selection and verifies that the
article list shows the right number of entries.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from newsgator.models.article import Article
from newsgator.models.database import (
    dispose_engine,
    get_engine,
    get_session_factory,
    init_db,
)
from newsgator.models.source import Source
from newsgator.ui.main_window import MainWindow
from newsgator.ui.source_panel import SourceSelection


async def _seed(db: Path) -> tuple[int, int]:
    await init_db(db)
    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    async with factory() as session:
        heise = Source(
            url="https://example.com/heise.xml",
            title="Heise",
            feed_type="rss",
            category="Tech",
        )
        veritasium = Source(
            url="https://example.com/veritasium.xml",
            title="Veritasium",
            feed_type="youtube",
            category="Wissenschaft",
        )
        session.add_all([heise, veritasium])
        await session.commit()
        await session.refresh(heise)
        await session.refresh(veritasium)

        for i in range(3):
            session.add(
                Article(
                    source_id=heise.id,
                    guid=f"heise:{i}",
                    title=f"Heise-Artikel {i}",
                    url=f"https://example.com/heise/{i}",
                    published_at=now - timedelta(hours=i),
                    is_read=(i == 0),  # one read
                )
            )
        for i in range(3):
            session.add(
                Article(
                    source_id=veritasium.id,
                    guid=f"yt:video:{i}",
                    title=f"Veritasium Video {i}",
                    url=f"https://youtube.com/watch?v={i}",
                    published_at=now - timedelta(hours=10 + i),
                    is_read=False,
                )
            )
        await session.commit()
        return heise.id, veritasium.id


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    received_articles: list[int] = []

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "articlelist-smoke.db"
        get_engine(db)
        factory = get_session_factory()
        window = MainWindow(factory)
        window.show()
        window.article_list.article_selected.connect(received_articles.append)

        async def _startup() -> None:
            heise_id, _ = await _seed(db)
            await window.refresh()

            cases: list[tuple[str, SourceSelection, int]] = [
                ("all",          SourceSelection(kind="all"),                                      6),
                ("category Tech", SourceSelection(kind="category", category="Tech"),               3),
                ("category Wiss.",SourceSelection(kind="category", category="Wissenschaft"),       3),
                ("source heise", SourceSelection(kind="source", source_id=heise_id, category="Tech"), 3),
            ]
            print(f"{'case':<18}  {'shown':>5}  expected")
            print(f"{'-'*18:<18}  {'-'*5:>5}  --------")
            for label, selection, expected in cases:
                await window.article_list.load_articles(selection)
                shown = window.article_list.entry_count()
                marker = "OK" if shown == expected else "FAIL"
                print(f"{label:<18}  {shown:>5}  {expected}  [{marker}]")
                assert shown == expected, f"{label}: expected {expected}, got {shown}"

            # Verify article_selected signal: select the first row
            view = window.article_list._view  # noqa: SLF001 — test access
            index = view.model().index(0, 0)
            view.setCurrentIndex(index)

            assert received_articles, "no article_selected signal emitted"
            print(f"\narticle_selected emitted with id={received_articles[-1]}")

            await dispose_engine()
            QTimer.singleShot(0, app.quit)

        loop.create_task(_startup())
        with loop:
            loop.run_forever()

    print("\nOK — article list filters and selection signal work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
