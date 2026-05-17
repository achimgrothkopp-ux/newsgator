"""Middle pane: list of articles matching the current sidebar selection.

Uses a small snapshot dataclass (``ArticleListEntry``) instead of handing
ORM objects to the model — by the time the UI paints them the AsyncSession
is long closed, and lazy attribute access on detached ORM objects raises.

Layout per row (72 px):

    ● Title of the article ...              [bold if unread]
      Source title · 2026-05-17 09:15       [grey, smaller]
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.article import Article
from newsgator.models.source import Source
from newsgator.ui.filter_toolbar import ArticleFilter, FilterToolbar
from newsgator.ui.source_panel import SourceSelection

logger = logging.getLogger(__name__)

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_HEIGHT = 72
ROW_PAD_X = 12
ROW_PAD_Y = 10
UNREAD_DOT_R = 4

UNREAD_DOT_COLOR = QColor("#2563eb")  # tailwind blue-600
META_COLOR = QColor("#6b7280")        # tailwind gray-500

LIST_LIMIT = 500


@dataclass(slots=True, frozen=True)
class ArticleListEntry:
    id: int
    title: str
    source_title: str
    published_at: datetime | None
    is_read: bool


async def fetch_entries(
    session_factory: async_sessionmaker[AsyncSession],
    selection: SourceSelection,
    article_filter: ArticleFilter | None = None,
) -> list[ArticleListEntry]:
    filt = article_filter or ArticleFilter()

    stmt = (
        select(Article, Source.title)
        .join(Source, Article.source_id == Source.id)
        .order_by(Article.published_at.desc().nulls_last(), Article.id.desc())
        .limit(LIST_LIMIT)
    )
    # Sidebar scope.
    if selection.kind == "source" and selection.source_id is not None:
        stmt = stmt.where(Article.source_id == selection.source_id)
    elif selection.kind == "category":
        if selection.category is None:
            stmt = stmt.where(Source.category.is_(None))
        else:
            stmt = stmt.where(Source.category == selection.category)
    # kind == "all": no sidebar filter

    # Toolbar overlay.
    if filt.unread_only:
        stmt = stmt.where(Article.is_read.is_(False))
    if filt.search:
        like = f"%{filt.search}%"
        stmt = stmt.where(
            or_(
                Article.title.ilike(like),
                Article.summary.ilike(like),
                Article.content.ilike(like),
            )
        )

    async with session_factory() as session:
        rows = (await session.execute(stmt)).all()

    return [
        ArticleListEntry(
            id=article.id,
            title=article.title,
            source_title=source_title,
            published_at=article.published_at,
            is_read=article.is_read,
        )
        for article, source_title in rows
    ]


class ArticleDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        entry: ArticleListEntry | None = index.data(ENTRY_ROLE)
        if entry is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Selection background.
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            text_color = option.palette.highlightedText().color()
            meta_color = text_color
        else:
            text_color = option.palette.text().color()
            meta_color = META_COLOR

        rect = option.rect.adjusted(ROW_PAD_X, ROW_PAD_Y, -ROW_PAD_X, -ROW_PAD_Y)

        # Unread dot, vertically aligned with the title baseline.
        if not entry.is_read:
            painter.setBrush(UNREAD_DOT_COLOR)
            painter.setPen(Qt.PenStyle.NoPen)
            cy = rect.top() + UNREAD_DOT_R + 4
            painter.drawEllipse(rect.left(), cy - UNREAD_DOT_R, UNREAD_DOT_R * 2, UNREAD_DOT_R * 2)

        text_left = rect.left() + (UNREAD_DOT_R * 2 + 8)

        # Title
        title_font: QFont = option.font
        title_font = QFont(title_font)
        title_font.setPointSizeF(title_font.pointSizeF() + 1)
        title_font.setBold(not entry.is_read)
        painter.setFont(title_font)
        painter.setPen(text_color)
        title_metrics = painter.fontMetrics()
        title = title_metrics.elidedText(
            entry.title, Qt.TextElideMode.ElideRight, rect.right() - text_left
        )
        painter.drawText(text_left, rect.top() + title_metrics.ascent() + 2, title)

        # Meta line: "source · date"
        meta_font = QFont(option.font)
        meta_font.setPointSizeF(meta_font.pointSizeF() - 1)
        painter.setFont(meta_font)
        painter.setPen(meta_color)
        meta_metrics = painter.fontMetrics()
        when = _format_when(entry.published_at)
        meta_line = f"{entry.source_title}  ·  {when}" if when else entry.source_title
        meta_line = meta_metrics.elidedText(
            meta_line, Qt.TextElideMode.ElideRight, rect.right() - text_left
        )
        painter.drawText(
            text_left,
            rect.bottom() - 4,
            meta_line,
        )

        painter.restore()


def _format_when(when: datetime | None) -> str:
    if when is None:
        return ""
    # The DB-stored datetimes are tz-aware (UTC). Convert to local for display.
    local = when.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


class ArticleListWidget(QWidget):
    article_selected = Signal(int)  # Article.id

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self._current_selection: SourceSelection | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toolbar = FilterToolbar()
        layout.addWidget(self._toolbar)

        self._view = QListView()
        self._model = QStandardItemModel(self._view)
        self._view.setModel(self._model)
        self._view.setItemDelegate(ArticleDelegate(self._view))
        self._view.setUniformItemSizes(True)
        self._view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        layout.addWidget(self._view, 1)

        self._toolbar.filter_changed.connect(self._on_filter_changed)

    def on_source_selection(self, selection: SourceSelection) -> None:
        """Slot connected to SourcePanel.selection_changed (sync entry point)."""
        asyncio.create_task(self.load_articles(selection))

    async def load_articles(self, selection: SourceSelection) -> None:
        self._current_selection = selection
        await self._apply()

    def _on_filter_changed(self, _filter: ArticleFilter) -> None:
        # No sidebar selection yet (startup); nothing to filter.
        if self._current_selection is None:
            return
        asyncio.create_task(self._apply())

    async def _apply(self) -> None:
        if self._current_selection is None:
            return
        filt = self._toolbar.current()
        entries = await fetch_entries(self._session_factory, self._current_selection, filt)
        self._populate(entries)
        logger.info(
            "article list: loaded %d entries for %s (filter=%s)",
            len(entries),
            self._current_selection,
            filt,
        )

    def _populate(self, entries: list[ArticleListEntry]) -> None:
        self._model.clear()
        for entry in entries:
            item = QStandardItem()
            item.setEditable(False)
            item.setData(entry, ENTRY_ROLE)
            self._model.appendRow(item)

    def entry_count(self) -> int:
        return self._model.rowCount()

    def mark_read(self, article_id: int) -> None:
        """Replace the entry for ``article_id`` with an is_read=True copy and
        request a repaint of that row. Called when ArticleView opens an item."""
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            entry: ArticleListEntry | None = item.data(ENTRY_ROLE)
            if entry is None or entry.id != article_id:
                continue
            if entry.is_read:
                return
            item.setData(replace(entry, is_read=True), ENTRY_ROLE)
            idx = self._model.index(row, 0)
            self._view.update(idx)
            return

    def _on_current_changed(self, current, _previous) -> None:
        if not current.isValid():
            return
        entry: ArticleListEntry | None = current.data(ENTRY_ROLE)
        if entry is not None:
            self.article_selected.emit(entry.id)
