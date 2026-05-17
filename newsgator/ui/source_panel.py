"""Left-hand sidebar: a tree of categories and their sources.

Emits a single ``selection_changed`` signal carrying a :class:`SourceSelection`
so downstream widgets (the article list) don't have to distinguish "kind"
based on which signal fired.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.source import Source

UNCATEGORIZED_LABEL = "(Ohne Kategorie)"
ALL_LABEL = "Alle Artikel"


@dataclass(slots=True, frozen=True)
class SourceSelection:
    """What the user picked in the sidebar."""

    kind: Literal["all", "category", "source"]
    source_id: int | None = None
    category: str | None = None


class SourcePanel(QWidget):
    selection_changed = Signal(object)  # SourceSelection

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._tree)

    async def reload(self) -> None:
        """Re-query sources and rebuild the tree. Keeps the current selection
        if it still exists, otherwise falls back to "Alle Artikel"."""
        async with self._session_factory() as session:
            stmt = select(Source).order_by(
                Source.category.is_(None),  # categorized first
                Source.category.asc(),
                Source.title.asc(),
            )
            sources = (await session.execute(stmt)).scalars().all()

        previous = self.current_selection()
        self._tree.blockSignals(True)
        self._tree.clear()

        all_item = QTreeWidgetItem([ALL_LABEL])
        all_item.setData(0, Qt.ItemDataRole.UserRole, SourceSelection(kind="all"))
        self._tree.addTopLevelItem(all_item)

        by_category: dict[str | None, list[Source]] = defaultdict(list)
        for s in sources:
            by_category[s.category].append(s)

        ordered_categories = sorted(
            by_category.keys(),
            key=lambda c: (c is None, (c or "").lower()),
        )
        for category in ordered_categories:
            cat_label = category if category is not None else UNCATEGORIZED_LABEL
            srcs = by_category[category]
            cat_item = QTreeWidgetItem([f"{cat_label}  ({len(srcs)})"])
            cat_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                SourceSelection(kind="category", category=category),
            )
            self._tree.addTopLevelItem(cat_item)
            for s in srcs:
                src_item = QTreeWidgetItem([s.title or s.url])
                src_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    SourceSelection(
                        kind="source",
                        source_id=s.id,
                        category=s.category,
                    ),
                )
                cat_item.addChild(src_item)

        self._tree.expandAll()
        self._tree.blockSignals(False)

        self._restore_selection(previous)

    def current_selection(self) -> SourceSelection | None:
        items = self._tree.selectedItems()
        if not items:
            return None
        value = items[0].data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, SourceSelection) else None

    def _restore_selection(self, previous: SourceSelection | None) -> None:
        target = previous
        if target is None:
            self._select_first()
            return

        found = self._find_item(target)
        if found is None:
            self._select_first()
            return
        found.setSelected(True)
        self._tree.setCurrentItem(found)

    def _select_first(self) -> None:
        if self._tree.topLevelItemCount() == 0:
            return
        first = self._tree.topLevelItem(0)
        first.setSelected(True)
        self._tree.setCurrentItem(first)

    def _find_item(self, target: SourceSelection) -> QTreeWidgetItem | None:
        # Top-level first
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top.data(0, Qt.ItemDataRole.UserRole) == target:
                return top
            for j in range(top.childCount()):
                child = top.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) == target:
                    return child
        return None

    def _on_selection_changed(self) -> None:
        selection = self.current_selection()
        if selection is not None:
            self.selection_changed.emit(selection)
