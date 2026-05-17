"""Modal dialog: create, rename or delete categories.

Two tables co-operate:

- ``categories`` is the registry of *declared* categories — what shows up
  in the AddSource dropdown.
- ``sources.category`` is the per-source assignment.

The dialog lists every name in ``categories`` together with the live count
of sources that reference it. Renaming/deleting cascades to both tables;
creating only inserts into the registry (no source uses it yet).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.category import Category
from newsgator.models.source import Source

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CategoryRow:
    name: str
    count: int


class CategoriesDialog(QDialog):
    """Create / rename / remove categories. Emits :attr:`changed` after each
    mutation so callers (the sidebar) can refresh."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(parent)
        self._session_factory = session_factory
        self.setWindowTitle("Kategorien verwalten")
        self.setMinimumSize(420, 360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Kategorien — Zahl in Klammern: zugewiesene Quellen. "
                "Leere Kategorien erscheinen erst im Sidebar-Baum, wenn "
                "eine Quelle sie nutzt."
            )
        )

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _it: self._on_rename())
        self._list.itemSelectionChanged.connect(self._update_button_state)
        layout.addWidget(self._list, 1)

        button_row = QHBoxLayout()
        self._new_btn = QPushButton("Neue Kategorie…")
        self._new_btn.clicked.connect(self._on_new)
        self._rename_btn = QPushButton("Umbenennen…")
        self._rename_btn.clicked.connect(self._on_rename)
        self._delete_btn = QPushButton("Entfernen")
        self._delete_btn.clicked.connect(self._on_delete)
        button_row.addWidget(self._new_btn)
        button_row.addWidget(self._rename_btn)
        button_row.addWidget(self._delete_btn)
        button_row.addStretch(1)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._update_button_state()
        # Defer the first DB load until the asyncio loop is actually running
        # (constructing during a non-running loop would raise).
        QTimer.singleShot(0, lambda: asyncio.create_task(self._reload()))

    # ---------- data --------------------------------------------------

    async def _reload(self) -> None:
        async with self._session_factory() as session:
            # Pull from categories registry; LEFT JOIN sources for live counts.
            stmt = (
                select(
                    Category.name,
                    func.count(Source.id),
                )
                .outerjoin(Source, Source.category == Category.name)
                .group_by(Category.name)
                .order_by(Category.name.asc())
            )
            rows = [
                CategoryRow(name=name, count=count)
                for name, count in (await session.execute(stmt)).all()
                if name
            ]

        self._list.clear()
        for row in rows:
            item = QListWidgetItem(f"{row.name}  ({row.count})")
            item.setData(0x0100, row.name)  # Qt.ItemDataRole.UserRole
            self._list.addItem(item)
        self._update_button_state()

    def _selected_category(self) -> str | None:
        items = self._list.selectedItems()
        if not items:
            return None
        return items[0].data(0x0100)

    def _update_button_state(self) -> None:
        enabled = self._selected_category() is not None
        self._rename_btn.setEnabled(enabled)
        self._delete_btn.setEnabled(enabled)

    # ---------- actions -----------------------------------------------

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Neue Kategorie", "Name der Kategorie:"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        asyncio.create_task(self._do_create(name))

    async def _do_create(self, name: str) -> None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(Category).where(Category.name == name)
            )
            if existing is not None:
                QMessageBox.information(
                    self,
                    "Kategorie existiert bereits",
                    f"'{name}' ist schon angelegt.",
                )
                return
            session.add(Category(name=name))
            await session.commit()
        logger.info("created category %r", name)
        # Intentionally NOT emitting `changed` here — an empty category does
        # not appear in the sidebar (which groups by Source.category), so
        # forcing a source_panel.reload would just kick the article list
        # for nothing. AddSource reads its dropdown on open, so it sees it.
        await self._reload()

    def _on_rename(self) -> None:
        current = self._selected_category()
        if current is None:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Kategorie umbenennen",
            f"Neuer Name für '{current}':",
            text=current,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == current:
            return
        asyncio.create_task(self._do_rename(current, new_name))

    async def _do_rename(self, old: str, new: str) -> None:
        async with self._session_factory() as session:
            target_exists = await session.scalar(
                select(Category).where(Category.name == new)
            )
            # Update sources first so the FK-ish string column points at the
            # surviving name, then collapse the registry entries.
            await session.execute(
                update(Source).where(Source.category == old).values(category=new)
            )
            if target_exists is None:
                await session.execute(
                    update(Category).where(Category.name == old).values(name=new)
                )
            else:
                # Merge — `old` rows now duplicate `new`; drop the old entry.
                await session.execute(
                    delete(Category).where(Category.name == old)
                )
            await session.commit()
        logger.info("renamed category %r -> %r", old, new)
        self.changed.emit()
        await self._reload()

    def _on_delete(self) -> None:
        current = self._selected_category()
        if current is None:
            return
        confirm = QMessageBox.question(
            self,
            "Kategorie entfernen",
            (
                f"Die Kategorie '{current}' entfernen? Sie wird aus der "
                "Auswahl gelöscht und von allen Quellen abgehängt — die "
                "Quellen selbst bleiben erhalten."
            ),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        asyncio.create_task(self._do_delete(current))

    async def _do_delete(self, name: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(Source).where(Source.category == name).values(category=None)
            )
            await session.execute(delete(Category).where(Category.name == name))
            await session.commit()
        logger.info("removed category %r", name)
        self.changed.emit()
        await self._reload()
