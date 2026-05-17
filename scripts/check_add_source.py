"""Headless smoke test for AddSourceDialog + the persist flow.

Tests three things:

1. AddSourceDialog as a pure widget: OK-Button gating, category combo
   pre-population, values() round-trip.
2. MainWindow._persist_new_source() inserts a new Source row, then the
   sidebar reload picks it up.
3. trigger_sync against a temp DB with one cheap source actually fetches
   and updates last_synced.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop
from sqlalchemy import select

from newsgator.models.database import (
    dispose_engine,
    get_engine,
    get_session_factory,
    init_db,
)
from newsgator.models.source import Source
from newsgator.ui.dialogs.add_source import AddSourceDialog, NewSourceSpec
from newsgator.ui.main_window import MainWindow


def _check_dialog_widget() -> None:
    dialog = AddSourceDialog(existing_categories=["Tech", "Wissenschaft"])

    # OK disabled until URL is plausible
    assert dialog._ok_button.isEnabled() is False  # noqa: SLF001
    dialog._url_edit.setText("not-a-url")  # noqa: SLF001
    assert dialog._ok_button.isEnabled() is False  # noqa: SLF001
    dialog._url_edit.setText("https://example.com/feed.xml")  # noqa: SLF001
    assert dialog._ok_button.isEnabled() is True  # noqa: SLF001
    print("dialog: OK-Button-Gating  [OK]")

    # Category combo is pre-populated with empty + existing
    items = [dialog._category_combo.itemText(i) for i in range(dialog._category_combo.count())]  # noqa: SLF001
    assert items == ["", "Tech", "Wissenschaft"], items
    print(f"dialog: category combo items = {items}  [OK]")

    # values() round-trip
    dialog._title_edit.setText("Example Blog")  # noqa: SLF001
    dialog._category_combo.setCurrentText("Blogs")  # noqa: SLF001 — new free-text category
    dialog._type_combo.setCurrentIndex(2)  # YouTube  # noqa: SLF001
    spec = dialog.values()
    assert spec == NewSourceSpec(
        feed_type="youtube",
        url="https://example.com/feed.xml",
        title="Example Blog",
        category="Blogs",
    ), spec
    print(f"dialog: values() = {spec}  [OK]")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    print("--- AddSourceDialog standalone ---")
    _check_dialog_widget()

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "addsource-smoke.db"
        get_engine(db)
        factory = get_session_factory()

        window = MainWindow(factory)
        window.show()

        async def _flow() -> None:
            await init_db()
            await window.refresh()

            print("\n--- _persist_new_source ---")
            spec = NewSourceSpec(
                feed_type="rss",
                url="https://www.heise.de/rss/heise-atom.xml",
                title="Heise",
                category="Tech",
            )
            await window._persist_new_source(spec)  # noqa: SLF001

            async with factory() as session:
                count = await session.scalar(select(Source).where(Source.url == spec.url))
                assert count is not None and count.title == "Heise", count
            print("persisted Heise source  [OK]")

            # Sidebar should now show the source under "Tech"
            tree = window.source_panel._tree  # noqa: SLF001
            tree_labels: list[str] = []
            for i in range(tree.topLevelItemCount()):
                top = tree.topLevelItem(i)
                tree_labels.append(top.text(0))
                for j in range(top.childCount()):
                    tree_labels.append("  " + top.child(j).text(0))
            print(f"sidebar after add: {tree_labels}")
            assert "Tech  (1)" in tree_labels and "  Heise" in tree_labels
            print("sidebar picked up new source  [OK]")

            # Duplicate add: QMessageBox.warning() is modal and would block
            # forever in offscreen mode, so patch it to a no-op for this call.
            with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
                await window._persist_new_source(spec)  # noqa: SLF001
            async with factory() as session:
                rows = (await session.execute(select(Source))).scalars().all()
            assert len(rows) == 1, f"duplicate inserted: {rows}"
            print("duplicate URL rejected  [OK]")

            print("\n--- trigger_sync (real network) ---")
            await window._sync_async()  # noqa: SLF001
            async with factory() as session:
                heise = await session.scalar(select(Source).where(Source.url == spec.url))
                assert heise is not None and heise.last_synced is not None
            print(f"sync updated last_synced = {heise.last_synced.isoformat()}  [OK]")
            print(f"status bar message: {window.statusBar().currentMessage()!r}")

            await dispose_engine()
            QTimer.singleShot(0, app.quit)

        loop.create_task(_flow())
        with loop:
            loop.run_forever()

    print("\nOK — dialog widget, persist flow and sync trigger all work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
