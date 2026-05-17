"""Top-level QMainWindow with the 3-panel layout.

Layout: Quellen-Sidebar (~220 px) | Artikel-Liste (~380 px) | Vorschau (rest).
The three panels are still placeholders — they'll be replaced by SourcePanel,
ArticleListWidget and ArticleView in the following steps.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


def _placeholder(title: str) -> QWidget:
    """Visible stand-in widget so the splitter has something to lay out."""
    panel = QFrame()
    panel.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(panel)
    label = QLabel(title)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("color: #888; font-size: 14px;")
    layout.addWidget(label)
    return panel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Newsgator")
        self.resize(1200, 800)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.source_panel = _placeholder("Quellen")
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
