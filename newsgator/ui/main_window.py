"""Top-level QMainWindow with the 3-panel layout.

Layout: Quellen-Sidebar (~220 px) | Artikel-Liste (~380 px) | Vorschau (rest).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.ui.article_list import ArticleListWidget
from newsgator.ui.article_view import ArticleView
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

        self.source_panel.selection_changed.connect(self.article_list.on_source_selection)
        self.article_list.article_selected.connect(self.article_view.on_article_selected)
        self.article_view.article_marked_read.connect(self.article_list.mark_read)

    async def refresh(self) -> None:
        """Reload the sidebar from DB. Called on startup and after a sync."""
        await self.source_panel.reload()
