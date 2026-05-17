"""Top-level QMainWindow with the 3-panel layout.

Layout: Quellen-Sidebar (~220 px) | Artikel-Liste (~380 px) | Vorschau (rest).
Article list and preview are still placeholders — they'll be replaced in the
following steps.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.ui.source_panel import SourcePanel, SourceSelection

logger = logging.getLogger(__name__)


def _placeholder(title: str) -> QWidget:
    panel = QFrame()
    panel.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(panel)
    label = QLabel(title)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("color: #888; font-size: 14px;")
    layout.addWidget(label)
    return panel


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
        self.article_list = _placeholder("Artikel")
        self.article_view = _placeholder("Vorschau")

        splitter.addWidget(self.source_panel)
        splitter.addWidget(self.article_list)
        splitter.addWidget(self.article_view)
        splitter.setSizes([220, 380, 600])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)

        self.setCentralWidget(splitter)

        self.source_panel.selection_changed.connect(self._on_source_selected)

    async def refresh(self) -> None:
        """Reload the sidebar from DB. Called on startup and after a sync."""
        await self.source_panel.reload()

    def _on_source_selected(self, selection: SourceSelection) -> None:
        # Wired up to the (real) article list in the next step.
        logger.info("selection: %s", selection)
