"""Headless smoke test for the filter toolbar.

Two angles:

1. ``fetch_entries`` with various ArticleFilter combinations against a seeded
   DB — verifies the SQL filtering.
2. ``FilterToolbar`` widget — toggle the checkbox and set search text, check
   that ``filter_changed`` carries the right ArticleFilter payload.
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
from newsgator.ui.article_list import fetch_entries
from newsgator.ui.filter_toolbar import ArticleFilter, FilterToolbar
from newsgator.ui.source_panel import SourceSelection


async def _seed(db: Path) -> None:
    await init_db(db)
    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    async with factory() as session:
        heise = Source(url="https://example.com/heise.xml", title="Heise", feed_type="rss")
        session.add(heise)
        await session.commit()
        await session.refresh(heise)

        articles = [
            # title,                    is_read, hours_ago, summary
            ("Python 3.13 erschienen",  False,   1, "<p>Neue Version mit JIT</p>"),
            ("Rust meets WebAssembly",  False,   2, "Performance-Vergleich"),
            ("Tagesschau-Update",       True,    3, "Innenpolitik aktuell"),
            ("Linux-Kernel 6.10",       False,   5, "Patch-Notes"),
            ("Apple M5 Geruechte",      True,    8, "Leaks aus Asien"),
        ]
        for i, (title, is_read, hours, summary) in enumerate(articles):
            session.add(
                Article(
                    source_id=heise.id,
                    guid=f"smoke:{i}",
                    title=title,
                    url=f"https://example.com/a/{i}",
                    published_at=now - timedelta(hours=hours),
                    summary=summary,
                    is_read=is_read,
                )
            )
        await session.commit()


async def _check_sql() -> None:
    factory = get_session_factory()
    sel_all = SourceSelection(kind="all")

    # 1. No filter -> all 5
    entries = await fetch_entries(factory, sel_all)
    assert len(entries) == 5, f"baseline: expected 5, got {len(entries)}"
    print(f"baseline (no filter):                    {len(entries)} entries  [OK]")

    # 2. unread_only -> 3 (Python, Rust, Linux)
    entries = await fetch_entries(factory, sel_all, ArticleFilter(unread_only=True))
    assert len(entries) == 3, f"unread_only: expected 3, got {len(entries)}"
    print(f"unread_only:                             {len(entries)} entries  [OK]")

    # 3. search "python" -> 1 (Python 3.13)
    entries = await fetch_entries(factory, sel_all, ArticleFilter(search="python"))
    assert len(entries) == 1 and "Python" in entries[0].title, entries
    print(f"search='python':                         {len(entries)} entries  [OK]")

    # 4. search hits summary too: "JIT"
    entries = await fetch_entries(factory, sel_all, ArticleFilter(search="JIT"))
    assert len(entries) == 1, f"search summary: got {len(entries)}"
    print(f"search='JIT' (matches summary):          {len(entries)} entries  [OK]")

    # 5. unread + search "Apple" -> 0 (Apple article is read)
    entries = await fetch_entries(
        factory, sel_all, ArticleFilter(unread_only=True, search="Apple")
    )
    assert len(entries) == 0, f"combined: got {len(entries)}"
    print(f"unread_only + search='Apple' (read art): {len(entries)} entries  [OK]")

    # 6. unread + search "Linux" -> 1
    entries = await fetch_entries(
        factory, sel_all, ArticleFilter(unread_only=True, search="Linux")
    )
    assert len(entries) == 1, f"combined ok: got {len(entries)}"
    print(f"unread_only + search='Linux':            {len(entries)} entries  [OK]")


def _check_widget() -> None:
    received: list[ArticleFilter] = []
    toolbar = FilterToolbar()
    toolbar.filter_changed.connect(received.append)

    # Toggle checkbox -> immediate emit
    toolbar._unread.setChecked(True)  # noqa: SLF001 — test access
    assert received and received[-1] == ArticleFilter(unread_only=True, search="")
    print(f"\ntoolbar: checkbox -> {received[-1]}  [OK]")

    # Set search text, then force-flush by stopping the debounce and calling _emit_now
    toolbar._search.setText("foo")  # noqa: SLF001
    toolbar._emit_now()              # noqa: SLF001 — skip the 250 ms wait
    assert received[-1] == ArticleFilter(unread_only=True, search="foo")
    print(f"toolbar: search='foo' -> {received[-1]}  [OK]")

    # Clear search
    toolbar._search.clear()  # noqa: SLF001
    toolbar._emit_now()      # noqa: SLF001
    assert received[-1] == ArticleFilter(unread_only=True, search="")
    print(f"toolbar: cleared search -> {received[-1]}  [OK]")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "filter-smoke.db"
        get_engine(db)

        async def _run() -> None:
            await _seed(db)
            print("--- SQL filter combinations -----------------------------------")
            await _check_sql()
            await dispose_engine()
            QTimer.singleShot(0, app.quit)

        loop.create_task(_run())
        with loop:
            loop.run_forever()

    # Widget test runs after the loop is done (no DB needed).
    print("--- toolbar widget --------------------------------------------------")
    _check_widget()

    print("\nOK — filter toolbar + fetch_entries combinations work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
