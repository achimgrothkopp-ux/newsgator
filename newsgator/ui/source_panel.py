"""Left-hand sidebar: a tree of categories and their sources.

Emits a single ``selection_changed`` signal carrying a :class:`SourceSelection`
so downstream widgets (the article list) don't have to distinguish "kind"
based on which signal fired.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QMenu,
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
ARCHIVED_LABEL = "Archiv"


def _matches(candidate: object, target: "SourceSelection") -> bool:
    """True if ``candidate`` represents the same user intent as ``target``.

    For source rows we compare by source_id alone so an edited source still
    counts as "the same row" even if its category changed. For categories
    and "all", exact equality is what we want.
    """
    if not isinstance(candidate, SourceSelection):
        return False
    if target.kind == "source":
        return candidate.kind == "source" and candidate.source_id == target.source_id
    return candidate == target


@dataclass(slots=True, frozen=True)
class SourceSelection:
    """What the user picked in the sidebar."""

    kind: Literal["all", "category", "source", "archived"]
    source_id: int | None = None
    category: str | None = None


class SourcePanel(QWidget):
    selection_changed = Signal(object)  # SourceSelection
    # Right-click on a source row → "Bearbeiten…" / "Löschen". Categories
    # and "Alle Artikel" have no context menu.
    source_edit_requested = Signal(int)
    source_delete_requested = Signal(int)

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory

        layout = QVBoxLayout(self)
        # Breathing room so items don't kiss the window edge on top or left.
        layout.setContentsMargins(8, 8, 0, 0)
        layout.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tree)

    async def reload(self) -> None:
        """Re-query sources and rebuild the tree. Keeps the current selection
        if it still exists, otherwise falls back to "Alle Artikel".

        Signals stay blocked across the whole rebuild — including the
        re-selection step — so we don't emit ``selection_changed`` purely
        because of the rebuild. We only re-emit at the end if the logical
        selection actually changed (different SourceSelection value).
        """
        async with self._session_factory() as session:
            stmt = select(Source).order_by(
                Source.category.is_(None),  # categorized first
                Source.category.asc(),
                Source.title.asc(),
            )
            sources = (await session.execute(stmt)).scalars().all()

        previous = self.current_selection()
        self._tree.blockSignals(True)
        try:
            self._tree.clear()

            all_item = QTreeWidgetItem([ALL_LABEL])
            all_item.setData(0, Qt.ItemDataRole.UserRole, SourceSelection(kind="all"))
            self._tree.addTopLevelItem(all_item)

            archived_item = QTreeWidgetItem([ARCHIVED_LABEL])
            archived_item.setData(
                0, Qt.ItemDataRole.UserRole, SourceSelection(kind="archived")
            )
            self._tree.addTopLevelItem(archived_item)

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
            self._restore_selection(previous)
        finally:
            self._tree.blockSignals(False)

        # Only fire downstream work if the user-visible selection actually
        # changed — a category create/rename that leaves the same source
        # selected should NOT re-load the article list.
        new_selection = self.current_selection()
        if new_selection is not None and new_selection != previous:
            self.selection_changed.emit(new_selection)

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
        # For source rows we match by source_id only — a category-rename or
        # source-edit may have changed the SourceSelection.category field,
        # but the user's intent ("keep this source selected") is preserved.
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if _matches(top.data(0, Qt.ItemDataRole.UserRole), target):
                return top
            for j in range(top.childCount()):
                child = top.child(j)
                if _matches(child.data(0, Qt.ItemDataRole.UserRole), target):
                    return child
        return None

    def _on_selection_changed(self) -> None:
        selection = self.current_selection()
        if selection is not None:
            self.selection_changed.emit(selection)

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(value, SourceSelection) or value.kind != "source":
            return
        if value.source_id is None:
            return

        menu = QMenu(self._tree)
        edit_action = menu.addAction("Bearbeiten…")
        delete_action = menu.addAction("Löschen")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is edit_action:
            self.source_edit_requested.emit(value.source_id)
        elif chosen is delete_action:
            self.source_delete_requested.emit(value.source_id)
