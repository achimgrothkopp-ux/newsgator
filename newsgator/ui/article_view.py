"""Right-hand pane: tabs for the rendered Reader and the original Webseite.

Two stacked views:

- **Reader** — ``QTextBrowser`` rendering the article's HTML (or summary).
  Lightweight, no JS, ideal for feed content.
- **Webseite** — ``QWebEngineView`` (Chromium) loading the original URL on
  demand when the user switches tabs. Lets the user keep videos, paywalled
  pages, etc. inside the app instead of jumping to the system browser.

If an article was unread when opened, it is marked read in the same load
step and the ``article_marked_read`` signal is emitted so the article list
can update its row without a full reload.
"""

from __future__ import annotations

import asyncio
import html as html_module
import logging
import re
from datetime import datetime

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QTabWidget, QTextBrowser, QVBoxLayout, QWidget
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.article import Article
from newsgator.models.source import Source
from newsgator.ui.settings import settings
from newsgator.ui.theme import ThemePalette, palette_for

READER_TAB = 0
WEB_TAB = 1

_FILENAME_BAD = re.compile(r"[^A-Za-z0-9._\-]+")

logger = logging.getLogger(__name__)


def _placeholder_html(palette: ThemePalette) -> str:
    return (
        f'<div style="color: {palette.fg_muted}; text-align: center; '
        'margin-top: 80px;">'
        "Wähle einen Artikel aus der Liste."
        "</div>"
    )


HTML_TAG_RE = re.compile(r"</[a-zA-Z]+>|<br\s*/?>", re.IGNORECASE)


class ArticleView(QWidget):
    article_marked_read = Signal(int)  # Article.id

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

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setHtml(_placeholder_html(palette_for(settings().theme())))
        self._tabs.addTab(self._browser, "Reader")

        self._web = QWebEngineView()
        self._tabs.addTab(self._web, "Webseite")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)

        # Kept around so File → "Artikel als HTML exportieren" can save
        # exactly what's on screen without re-querying the DB. Article-ID
        # is held too so a settings change can re-render in place.
        self._current_html: str | None = None
        self._current_title: str | None = None
        self._current_article_id: int | None = None
        self._current_url: str | None = None
        # Last URL handed to the QWebEngineView — avoids redundant reloads
        # when the user just toggles tabs.
        self._loaded_web_url: str | None = None
        # Track the in-flight article load so a rapid second selection can
        # cancel the previous one instead of marking-as-read in cascade.
        self._load_task: asyncio.Task[None] | None = None

        settings().changed.connect(self._on_settings_changed)

    def on_article_selected(self, article_id: int) -> None:
        """Slot for ArticleListWidget.article_selected (sync entry point)."""
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._load_task = asyncio.create_task(self.load_article(article_id))

    def clear(self) -> None:
        """Reset the pane to its placeholder — used when the sidebar
        selection changes so the previous source's article doesn't linger."""
        self._browser.setHtml(_placeholder_html(palette_for(settings().theme())))
        self._web.setUrl(QUrl("about:blank"))
        self._tabs.setCurrentIndex(READER_TAB)
        self._current_html = None
        self._current_title = None
        self._current_article_id = None
        self._current_url = None
        self._loaded_web_url = None

    def _on_settings_changed(self) -> None:
        if self._current_article_id is None:
            self._browser.setHtml(_placeholder_html(palette_for(settings().theme())))
            return
        # Route through the cancel-previous path so we don't pile up loads.
        self.on_article_selected(self._current_article_id)

    def current_html(self) -> str | None:
        """Return the rendered HTML of the article on screen, or ``None``
        when the pane is showing the placeholder."""
        return self._current_html

    def suggested_filename(self) -> str | None:
        """Filesystem-safe filename derived from the current article title."""
        if not self._current_title:
            return None
        stem = _FILENAME_BAD.sub("-", self._current_title).strip("-")
        return (stem[:80] or "artikel") + ".html"

    async def load_article(self, article_id: int) -> None:
        s = settings()
        palette = palette_for(s.theme())
        async with self._session_factory() as session:
            article = await session.get(Article, article_id)
            if article is None:
                self._browser.setHtml(_placeholder_html(palette))
                return

            source_title = ""
            if article.source_id is not None:
                source = await session.get(Source, article.source_id)
                if source is not None:
                    source_title = source.title or source.url

            was_unread = not article.is_read
            if was_unread:
                article.is_read = True
                await session.commit()

            html = _render_article(
                article,
                source_title,
                palette=palette,
                font_family=s.font_family(),
                font_size_pt=s.font_size_pt(),
            )
            self._current_title = article.title

        self._current_html = html
        self._current_article_id = article_id
        self._current_url = article.url or None
        self._browser.setHtml(html)

        # If the user is already on the Webseite tab, swap the URL right away;
        # otherwise let _on_tab_changed handle it lazily on first switch.
        if self._tabs.currentIndex() == WEB_TAB:
            self._load_web_if_needed()

        if was_unread:
            self.article_marked_read.emit(article_id)
            logger.info("article %d marked as read", article_id)

    def _on_tab_changed(self, index: int) -> None:
        if index == WEB_TAB:
            self._load_web_if_needed()

    def _load_web_if_needed(self) -> None:
        url = self._current_url
        if not url:
            self._web.setUrl(QUrl("about:blank"))
            self._loaded_web_url = None
            return
        if url == self._loaded_web_url:
            return
        self._web.setUrl(QUrl(url))
        self._loaded_web_url = url


def _render_article(
    article: Article,
    source_title: str,
    *,
    palette: ThemePalette,
    font_family: str,
    font_size_pt: int,
) -> str:
    title = html_module.escape(article.title or "(ohne Titel)")
    source_safe = html_module.escape(source_title) if source_title else ""
    when = _format_when(article.published_at)

    meta_parts = [p for p in (source_safe, when) if p]
    meta_line = "  ·  ".join(meta_parts)
    if article.url:
        url_safe = html_module.escape(article.url)
        meta_line = (
            f"{meta_line}  ·  " if meta_line else ""
        ) + f'<a href="{url_safe}">Original öffnen ›</a>'

    body = _format_content(article.content, article.summary, palette=palette)

    return (
        "<html><body style="
        f'"font-family: {font_family}; font-size: {font_size_pt}pt; '
        f"color: {palette.fg}; background-color: {palette.bg}; "
        'padding: 16px;">'
        f'<h1 style="margin-bottom: 4px;">{title}</h1>'
        f'<p style="color: {palette.fg_muted}; margin-top: 0;">{meta_line}</p>'
        f'<hr style="border: none; border-top: 1px solid {palette.separator};">'
        f"{body}"
        "</body></html>"
    )


def _format_when(when: datetime | None) -> str:
    if when is None:
        return ""
    return when.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_content(
    content: str | None,
    summary: str | None,
    *,
    palette: ThemePalette,
) -> str:
    raw = (content or summary or "").strip()
    if not raw:
        return (
            f'<p style="color: {palette.fg_muted};">'
            "<em>(Kein Inhalt extrahiert.)</em></p>"
        )

    # If we already see a closing tag or <br>, treat the payload as HTML.
    # RSS content arrives as HTML; trafilatura's default extract is plain text.
    if HTML_TAG_RE.search(raw):
        return raw

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw)]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return f"<p>{html_module.escape(raw).replace(chr(10), '<br>')}</p>"
    return "\n".join(
        f"<p>{html_module.escape(p).replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )
