"""Top-level QMainWindow with the 3-panel layout.

Layout: Quellen-Sidebar (~220 px) | Artikel-Liste (~380 px) | Vorschau (rest).
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QMainWindow, QMessageBox, QSplitter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.source import Source
from newsgator.sync.scheduler import FeedScheduler
from newsgator.ui.article_list import ArticleListWidget
from newsgator.ui.article_view import ArticleView
from newsgator.ui.dialogs.add_source import AddSourceDialog, NewSourceSpec
from newsgator.ui.source_panel import SourcePanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self.setWindowTitle("Newsgator")
        self.resize(1200, 800)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.source_panel = SourcePanel(session_factory)
        self.article_list = ArticleListWidget(session_factory)
        self.article_view = ArticleView(session_factory)

        splitter.addWidget(self.source_panel)
        splitter.addWidget(self.article_list)
        splitter.addWidget(self.article_view)
        splitter.setSizes([220, 380, 600])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)

        self.setCentralWidget(splitter)

        self._build_menus()
        self.statusBar().showMessage("Bereit")

        self.source_panel.selection_changed.connect(self.article_list.on_source_selection)
        self.source_panel.selection_changed.connect(lambda _sel: self.article_view.clear())
        self.article_list.article_selected.connect(self.article_view.on_article_selected)
        self.article_view.article_marked_read.connect(self.article_list.mark_read)

    async def refresh(self) -> None:
        """Reload the sidebar from DB. Called on startup and after a sync."""
        await self.source_panel.reload()

    # ---------- menu ----------------------------------------------------

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&Datei")

        new_source = QAction("&Neue Quelle…", self)
        new_source.setShortcut(QKeySequence("Ctrl+N"))
        new_source.triggered.connect(self.open_add_source_dialog)
        file_menu.addAction(new_source)

        refresh = QAction("&Aktualisieren", self)
        refresh.setShortcut(QKeySequence("Ctrl+R"))
        refresh.triggered.connect(self.trigger_sync)
        file_menu.addAction(refresh)

        file_menu.addSeparator()

        quit_action = QAction("&Beenden", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # ---------- new source flow ----------------------------------------

    def open_add_source_dialog(self) -> None:
        asyncio.create_task(self._open_add_source_async())

    async def _open_add_source_async(self) -> None:
        async with self._session_factory() as session:
            stmt = (
                select(Source.category)
                .where(Source.category.is_not(None))
                .distinct()
                .order_by(Source.category.asc())
            )
            categories = [c for c in (await session.execute(stmt)).scalars().all() if c]

        dialog = AddSourceDialog(self, existing_categories=categories)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        await self._persist_new_source(dialog.values())

    async def _persist_new_source(self, spec: NewSourceSpec) -> None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(Source).where(Source.url == spec.url)
            )
            if existing is not None:
                QMessageBox.warning(
                    self,
                    "Quelle existiert bereits",
                    f"Diese URL ist schon als Quelle #{existing.id} hinterlegt.",
                )
                return
            src = Source(
                url=spec.url,
                title=spec.title or spec.url,
                feed_type=spec.feed_type,
                category=spec.category or None,
            )
            session.add(src)
            await session.commit()

        await self.source_panel.reload()
        self.statusBar().showMessage(
            f"Quelle hinzugefügt: {spec.title or spec.url}", 5000
        )

    # ---------- sync flow ----------------------------------------------

    def trigger_sync(self) -> None:
        asyncio.create_task(self._sync_async())

    async def _sync_async(self) -> None:
        self.statusBar().showMessage("Synchronisiere…")
        scheduler = FeedScheduler(self._session_factory)
        results = await scheduler.sync_all()
        total_new = sum(r.new_articles for r in results)
        errors = sum(1 for r in results if r.error)
        msg = f"Sync fertig: {total_new} neue Artikel"
        if errors:
            msg += f", {errors} Fehler (siehe Log)"
        self.statusBar().showMessage(msg, 8000)
        await self.source_panel.reload()
        await self.article_list.reload_current()
