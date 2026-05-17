"""Headless smoke test for ArticleView.

Seeds one source + one unread article, opens it via load_article(), and
verifies:

- the rendered HTML in QTextBrowser contains the title and source name,
- the article row in the DB now has is_read=True,
- the article_marked_read signal fired with the right id,
- the article list's snapshot for that row also reports is_read=True.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop
from sqlalchemy import select

from newsgator.models.article import Article
from newsgator.models.database import (
    dispose_engine,
    get_engine,
    get_session_factory,
    init_db,
)
from newsgator.models.source import Source
from newsgator.ui.article_list import ENTRY_ROLE, ArticleListEntry
from newsgator.ui.main_window import MainWindow
from newsgator.ui.source_panel import SourceSelection


async def _seed(db: Path) -> int:
    await init_db(db)
    factory = get_session_factory()
    async with factory() as session:
        src = Source(
            url="https://example.com/heise.xml",
            title="Heise",
            feed_type="rss",
            category="Tech",
        )
        session.add(src)
        await session.commit()
        await session.refresh(src)

        article = Article(
            source_id=src.id,
            guid="example:1",
            title="Großer Test-Artikel",
            url="https://example.com/article/1",
            published_at=datetime.now(timezone.utc),
            summary="<p>Eine kurze HTML-Zusammenfassung mit <strong>Hervorhebung</strong>.</p>",
            content="<p>Lange Inhaltszeile, ebenfalls HTML.</p>",
            is_read=False,
        )
        session.add(article)
        await session.commit()
        await session.refresh(article)
        return article.id


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    marked_read: list[int] = []

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "articleview-smoke.db"
        get_engine(db)
        factory = get_session_factory()
        window = MainWindow(factory)
        window.show()
        window.article_view.article_marked_read.connect(marked_read.append)

        async def _startup() -> None:
            article_id = await _seed(db)
            await window.refresh()
            # Bring the article into the list so mark_read can find it.
            await window.article_list.load_articles(SourceSelection(kind="all"))

            # Open the article.
            await window.article_view.load_article(article_id)

            # Inspect the rendered HTML.
            rendered = window.article_view._browser.toHtml()  # noqa: SLF001
            assert "Großer Test-Artikel" in rendered, "title missing in HTML"
            assert "Heise" in rendered, "source title missing in HTML"
            assert "example.com/article/1" in rendered, "original-link missing"
            print("rendered HTML contains: title, source, original-link  [OK]")

            # DB should now report is_read=True.
            async with factory() as session:
                stored = (
                    await session.execute(select(Article).where(Article.id == article_id))
                ).scalar_one()
                assert stored.is_read is True, "is_read flag not persisted"
            print("DB is_read=True  [OK]")

            # Signal must have fired once with the article id.
            assert marked_read == [article_id], f"unexpected signal log: {marked_read}"
            print(f"article_marked_read fired with id={article_id}  [OK]")

            # Article list snapshot for that row should now report is_read=True.
            model = window.article_list._model  # noqa: SLF001
            entry: ArticleListEntry | None = None
            for row in range(model.rowCount()):
                e = model.item(row).data(ENTRY_ROLE)
                if e.id == article_id:
                    entry = e
                    break
            assert entry is not None and entry.is_read is True, entry
            print("article list snapshot is_read=True  [OK]")

            # Re-opening should not fire the signal again.
            await window.article_view.load_article(article_id)
            assert marked_read == [article_id], "signal fired on re-open"
            print("re-opening read article does not re-emit signal  [OK]")

            await dispose_engine()
            QTimer.singleShot(0, app.quit)

        loop.create_task(_startup())
        with loop:
            loop.run_forever()

    print("\nOK — preview renders, mark-as-read round-trip works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
