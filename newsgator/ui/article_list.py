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
from newsgator.ui.settings import settings
from newsgator.ui.source_panel import SourceSelection
from newsgator.ui.theme import palette_for

logger = logging.getLogger(__name__)

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_HEIGHT = 72
ROW_PAD_X = 12
ROW_PAD_Y = 10
UNREAD_DOT_R = 4

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
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._refresh_palette()
        settings().changed.connect(self._refresh_palette)

    def _refresh_palette(self) -> None:
        p = palette_for(settings().theme())
        self._sel_bg = QColor(p.selection_bg)
        self._sel_fg = QColor(p.selection_fg)
        self._fg = QColor(p.fg)
        self._meta = QColor(p.fg_muted)
        self._dim = QColor(p.fg_dim)
        self._accent = QColor(p.accent)
        self._separator = QColor(p.separator)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        entry: ArticleListEntry | None = index.data(ENTRY_ROLE)
        if entry is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Selection background takes precedence over read/unread colors:
        # otherwise grey-on-blue is unreadable when a read row is selected.
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, self._sel_bg)
            text_color = self._sel_fg
            meta_color = self._meta
        elif entry.is_read:
            text_color = self._dim
            meta_color = self._dim
        else:
            text_color = self._fg
            meta_color = self._meta

        rect = option.rect.adjusted(ROW_PAD_X, ROW_PAD_Y, -ROW_PAD_X, -ROW_PAD_Y)

        # Unread dot, vertically aligned with the title baseline.
        if not entry.is_read:
            painter.setBrush(self._accent)
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

        # Hairline separator at the bottom edge of every row except the
        # selected one (where it would cut across the highlight).
        if not (option.state & QStyle.StateFlag.State_Selected):
            painter.setPen(self._separator)
            y = option.rect.bottom()
            painter.drawLine(option.rect.left(), y, option.rect.right(), y)

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
        # Track the in-flight load so a rapid second sidebar change can
        # cancel it instead of racing two _populate calls into the model.
        self._load_task: asyncio.Task[None] | None = None

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

        # Theme/font changes: delegate updates its color cache on its own,
        # we just have to nudge the view to repaint.
        settings().changed.connect(self._view.viewport().update)

    def on_source_selection(self, selection: SourceSelection) -> None:
        """Slot connected to SourcePanel.selection_changed (sync entry point)."""
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._load_task = asyncio.create_task(self.load_articles(selection))

    async def load_articles(self, selection: SourceSelection) -> None:
        # Sidebar change: jump to the first article of the new scope so the
        # preview pane fills immediately instead of sitting on a placeholder.
        self._current_selection = selection
        await self._apply(auto_select_first=True)

    async def reload_current(self) -> None:
        """Re-run the current filter+selection query. Used after a sync."""
        if self._current_selection is None:
            return
        await self._apply(auto_select_first=False)

    def _on_filter_changed(self, _filter: ArticleFilter) -> None:
        # No sidebar selection yet (startup); nothing to filter.
        if self._current_selection is None:
            return
        asyncio.create_task(self._apply(auto_select_first=False))

    async def _apply(self, auto_select_first: bool = False) -> None:
        if self._current_selection is None:
            return
        filt = self._toolbar.current()
        entries = await fetch_entries(self._session_factory, self._current_selection, filt)
        self._populate(entries, auto_select_first=auto_select_first)
        logger.info(
            "article list: loaded %d entries for %s (filter=%s)",
            len(entries),
            self._current_selection,
            filt,
        )

    def _populate(
        self,
        entries: list[ArticleListEntry],
        *,
        auto_select_first: bool = False,
    ) -> None:
        previous_id = self._current_article_id()
        self._model.clear()
        for entry in entries:
            item = QStandardItem()
            item.setEditable(False)
            item.setData(entry, ENTRY_ROLE)
            self._model.appendRow(item)

        if self._model.rowCount() == 0:
            return

        # Try to keep the previously open article visible across reloads /
        # filter changes; otherwise fall back to the first row when the caller
        # asked for an auto-jump (sidebar change).
        target_row: int | None = None
        if previous_id is not None:
            target_row = self._row_for_article(previous_id)
        if target_row is None and auto_select_first:
            target_row = 0
        if target_row is not None:
            self._view.setCurrentIndex(self._model.index(target_row, 0))

    def entry_count(self) -> int:
        return self._model.rowCount()

    def _current_article_id(self) -> int | None:
        idx = self._view.currentIndex()
        if not idx.isValid():
            return None
        entry: ArticleListEntry | None = idx.data(ENTRY_ROLE)
        return entry.id if entry is not None else None

    def _row_for_article(self, article_id: int) -> int | None:
        for row in range(self._model.rowCount()):
            entry: ArticleListEntry | None = self._model.item(row).data(ENTRY_ROLE)
            if entry is not None and entry.id == article_id:
                return row
        return None

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
