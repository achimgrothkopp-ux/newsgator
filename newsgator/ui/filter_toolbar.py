"""Toolbar above the article list: unread-only toggle + search box.

Source/category filtering is the sidebar's job — this toolbar layers on top
of whichever subset the sidebar selected.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

SEARCH_DEBOUNCE_MS = 250


@dataclass(slots=True, frozen=True)
class ArticleFilter:
    """Toolbar state applied on top of the sidebar selection."""

    unread_only: bool = False
    search: str = ""


class FilterToolbar(QWidget):
    filter_changed = Signal(object)  # ArticleFilter

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._unread = QCheckBox("Nur ungelesen")
        self._unread.toggled.connect(self._emit_now)
        layout.addWidget(self._unread)

        layout.addStretch(1)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Suche …")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(180)
        self._search.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self._search)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._emit_now)

    # --- API -----------------------------------------------------------

    def current(self) -> ArticleFilter:
        return ArticleFilter(
            unread_only=self._unread.isChecked(),
            search=self._search.text().strip(),
        )

    # --- internal ------------------------------------------------------

    def _on_search_text_changed(self, _text: str) -> None:
        # Debounce: don't hit the DB on every keystroke.
        self._search_timer.start()

    def _emit_now(self) -> None:
        self._search_timer.stop()
        self.filter_changed.emit(self.current())
