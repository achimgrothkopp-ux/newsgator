"""Top-level QMainWindow with the 3-panel layout.

Layout: Quellen-Sidebar (~220 px) | Artikel-Liste (~380 px) | Vorschau (rest).
"""

from __future__ import annotations

import asyncio
import logging

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.category import Category
from newsgator.models.source import Source
from newsgator.sync.scheduler import FeedScheduler
from newsgator.ui.article_list import ArticleListWidget
from newsgator.ui.article_view import ArticleView
from newsgator.ui.dialogs.add_source import AddSourceDialog, NewSourceSpec
from newsgator.ui.dialogs.categories import CategoriesDialog
from newsgator.ui.dialogs.settings import SettingsDialog
from newsgator.ui.settings import settings
from newsgator.ui.source_panel import SourcePanel
from newsgator.ui.theme import build_stylesheet, palette_for
from newsgator.utils.opml import OpmlEntry, build_opml, parse_opml

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
        self._apply_theme()
        settings().changed.connect(self._apply_theme)

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

    # ---------- theme ---------------------------------------------------

    def _apply_theme(self) -> None:
        s = settings()
        palette = palette_for(s.theme())
        self.setStyleSheet(
            build_stylesheet(
                palette, font_family=s.font_family(), font_size_pt=s.font_size_pt()
            )
        )

    # ---------- menu ----------------------------------------------------

    def _build_menus(self) -> None:
        bar = self.menuBar()

        # --- Datei ---------------------------------------------------
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

        settings_action = QAction("&Einstellungen…", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        quit_action = QAction("&Beenden", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # --- Feed-Verwaltung ----------------------------------------
        feeds_menu = bar.addMenu("&Feed-Verwaltung")

        manage_cats = QAction("&Kategorien verwalten…", self)
        manage_cats.triggered.connect(self.open_categories_dialog)
        feeds_menu.addAction(manage_cats)

        feeds_menu.addSeparator()

        opml_import = QAction("OPML &importieren…", self)
        opml_import.triggered.connect(self.import_opml)
        feeds_menu.addAction(opml_import)

        opml_export = QAction("OPML &exportieren…", self)
        opml_export.triggered.connect(self.export_opml)
        feeds_menu.addAction(opml_export)

        feeds_menu.addSeparator()

        export_html = QAction("Aktuellen Artikel als &HTML speichern…", self)
        export_html.triggered.connect(self.export_current_article_html)
        feeds_menu.addAction(export_html)

        # --- Hilfe --------------------------------------------------
        help_menu = bar.addMenu("&Hilfe")
        about = QAction("&Über Newsgator…", self)
        about.triggered.connect(self.open_about_dialog)
        help_menu.addAction(about)

    # ---------- menu handler stubs -------------------------------------

    def open_settings_dialog(self) -> None:
        SettingsDialog(self).exec()

    def open_categories_dialog(self) -> None:
        dialog = CategoriesDialog(self, self._session_factory)
        dialog.changed.connect(lambda: asyncio.create_task(self.source_panel.reload()))
        dialog.exec()

    def import_opml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "OPML-Datei importieren",
            str(Path.home()),
            "OPML-Dateien (*.opml *.xml);;Alle Dateien (*)",
        )
        if not path:
            return
        asyncio.create_task(self._import_opml_async(Path(path)))

    async def _import_opml_async(self, path: Path) -> None:
        try:
            xml_text = path.read_text(encoding="utf-8")
            entries = parse_opml(xml_text)
        except Exception as exc:  # noqa: BLE001 - surface any parse failure
            logger.exception("OPML parse failed")
            QMessageBox.critical(self, "OPML-Import fehlgeschlagen", str(exc))
            return

        added = 0
        skipped = 0
        async with self._session_factory() as session:
            existing_urls = set(
                (await session.execute(select(Source.url))).scalars().all()
            )
            registered_cats = set(
                (await session.execute(select(Category.name))).scalars().all()
            )
            for entry in entries:
                if entry.url in existing_urls:
                    skipped += 1
                    continue
                session.add(
                    Source(
                        url=entry.url,
                        title=entry.title or entry.url,
                        feed_type=entry.feed_type,
                        category=entry.category,
                    )
                )
                existing_urls.add(entry.url)
                if entry.category and entry.category not in registered_cats:
                    session.add(Category(name=entry.category))
                    registered_cats.add(entry.category)
                added += 1
            await session.commit()

        await self.source_panel.reload()
        self.statusBar().showMessage(
            f"OPML-Import: {added} neu, {skipped} übersprungen", 8000
        )

    def export_opml(self) -> None:
        default = str(Path.home() / "newsgator-feeds.opml")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "OPML exportieren",
            default,
            "OPML-Dateien (*.opml);;Alle Dateien (*)",
        )
        if not path:
            return
        asyncio.create_task(self._export_opml_async(Path(path)))

    async def _export_opml_async(self, path: Path) -> None:
        async with self._session_factory() as session:
            sources = (
                await session.execute(select(Source).order_by(Source.title.asc()))
            ).scalars().all()
        entries = [
            OpmlEntry(
                feed_type=s.feed_type,
                url=s.url,
                title=s.title or s.url,
                category=s.category,
            )
            for s in sources
        ]
        try:
            path.write_text(build_opml(entries), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "OPML-Export fehlgeschlagen", str(exc))
            return
        self.statusBar().showMessage(
            f"OPML-Export: {len(entries)} Quellen → {path.name}", 8000
        )

    def export_current_article_html(self) -> None:
        # Re-uses whatever the article view currently has rendered, so the
        # exported file matches what the user sees in the preview pane.
        html = self.article_view.current_html()
        if html is None:
            QMessageBox.information(
                self,
                "Kein Artikel ausgewählt",
                "Bitte zuerst einen Artikel auswählen.",
            )
            return
        suggested = self.article_view.suggested_filename() or "artikel.html"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Artikel als HTML speichern",
            str(Path.home() / suggested),
            "HTML-Dateien (*.html);;Alle Dateien (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(html, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "HTML-Export fehlgeschlagen", str(exc))
            return
        self.statusBar().showMessage(f"Artikel gespeichert: {Path(path).name}", 6000)

    def open_about_dialog(self) -> None:
        from newsgator import __version__ as version

        QMessageBox.about(
            self,
            "Über Newsgator",
            (
                f"<h3>Newsgator {version}</h3>"
                "<p>Linux Desktop-Newsreader für RSS/Atom, HTTP-Seiten "
                "und YouTube-Kanäle.</p>"
                "<p>Autor: Achim Grothkopp<br>"
                'Lizenz: MIT</p>'
            ),
        )

    # ---------- new source flow ----------------------------------------

    def open_add_source_dialog(self) -> None:
        asyncio.create_task(self._open_add_source_async())

    async def _open_add_source_async(self) -> None:
        async with self._session_factory() as session:
            # Registry first, then any in-use values that aren't registered
            # (defensive — backfill should have caught these already).
            registered = set(
                (await session.execute(select(Category.name))).scalars().all()
            )
            in_use = set(
                c
                for c in (
                    await session.execute(
                        select(Source.category).where(Source.category.is_not(None))
                    )
                ).scalars().all()
                if c
            )
            categories = sorted(registered | in_use, key=str.lower)

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
            # Make sure a freshly-typed category from the AddSource "+" button
            # also lands in the registry so the next AddSource sees it.
            if spec.category:
                exists = await session.scalar(
                    select(Category).where(Category.name == spec.category)
                )
                if exists is None:
                    session.add(Category(name=spec.category))
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
