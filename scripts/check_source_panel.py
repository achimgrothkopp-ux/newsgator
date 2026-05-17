"""Headless smoke test: seed a temp DB with sources across categories,
launch MainWindow, walk the tree and verify structure + selection-signal."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QTreeWidget
from qasync import QEventLoop

from newsgator.models.database import (
    dispose_engine,
    get_engine,
    get_session_factory,
    init_db,
)
from newsgator.models.source import Source
from newsgator.ui.main_window import MainWindow
from newsgator.ui.source_panel import SourceSelection

SEED: list[tuple[str, str, str, str | None]] = [
    ("rss",     "Heise",         "https://www.heise.de/rss/heise-atom.xml",          "Tech"),
    ("rss",     "Golem",         "https://rss.golem.de/rss.php?feed=ATOM1.0",        "Tech"),
    ("youtube", "Veritasium",    "https://www.youtube.com/@veritasium",              "Wissenschaft"),
    ("http",    "uv Docs",       "https://docs.astral.sh/uv/getting-started/",       None),
]


async def _seed(db: Path) -> None:
    await init_db(db)
    session_factory = get_session_factory()
    async with session_factory() as session:
        for feed_type, title, url, category in SEED:
            session.add(Source(url=url, title=title, feed_type=feed_type, category=category))
        await session.commit()


def _dump_tree(tree: QTreeWidget) -> list[str]:
    lines: list[str] = []
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        lines.append(f"- {top.text(0)}")
        for j in range(top.childCount()):
            lines.append(f"    - {top.child(j).text(0)}")
    return lines


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    received: list[SourceSelection] = []

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sourcepanel-smoke.db"
        get_engine(db)  # bind the global engine to our temp DB first
        session_factory = get_session_factory()

        window = MainWindow(session_factory)
        window.show()
        window.source_panel.selection_changed.connect(received.append)

        async def _startup() -> None:
            await _seed(db)
            await window.refresh()

            tree = window.source_panel._tree
            print("Tree contents:")
            for line in _dump_tree(tree):
                print("  " + line)

            assert tree.topLevelItemCount() == 4, (
                f"expected 4 top-level items (Alle + 2 categories + Uncategorized), "
                f"got {tree.topLevelItemCount()}"
            )

            # "Alle Artikel" must be selected by default
            current = window.source_panel.current_selection()
            assert current is not None and current.kind == "all", current
            print(f"\nInitial selection: {current}")
            assert received and received[-1].kind == "all", received

            # Click the second category's first child (a source)
            tech_item = tree.topLevelItem(1)
            print(f"\nClicking child of: {tech_item.text(0)}")
            first_source = tech_item.child(0)
            first_source.setSelected(True)
            tree.setCurrentItem(first_source)

            sel = window.source_panel.current_selection()
            assert sel is not None and sel.kind == "source", sel
            print(f"Source selection: {sel}")

            await dispose_engine()
            QTimer.singleShot(0, app.quit)

        loop.create_task(_startup())
        with loop:
            loop.run_forever()

    print(f"\nReceived {len(received)} selection_changed events")
    print("OK — sidebar populated, selection round-trip works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
