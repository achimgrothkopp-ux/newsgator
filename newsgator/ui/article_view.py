"""Right-hand pane: rich-text preview of the selected article.

Uses ``QTextBrowser`` (not ``QWebEngineView``) because:

- It ships with PySide6, no extra package or sandbox setup needed.
- Qt's rich-text engine handles the HTML we get from RSS feeds well enough
  for a reader view; we don't need JS, modern CSS, or layout features.

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

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsgator.models.article import Article
from newsgator.models.source import Source

logger = logging.getLogger(__name__)

PLACEHOLDER_HTML = (
    '<div style="color: #6b7280; text-align: center; margin-top: 80px;">'
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

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setHtml(PLACEHOLDER_HTML)
        layout.addWidget(self._browser)

    def on_article_selected(self, article_id: int) -> None:
        """Slot for ArticleListWidget.article_selected (sync entry point)."""
        asyncio.create_task(self.load_article(article_id))

    def clear(self) -> None:
        """Reset the pane to its placeholder — used when the sidebar
        selection changes so the previous source's article doesn't linger."""
        self._browser.setHtml(PLACEHOLDER_HTML)

    async def load_article(self, article_id: int) -> None:
        async with self._session_factory() as session:
            article = await session.get(Article, article_id)
            if article is None:
                self._browser.setHtml(PLACEHOLDER_HTML)
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

            html = _render_article(article, source_title)

        self._browser.setHtml(html)
        if was_unread:
            self.article_marked_read.emit(article_id)
            logger.info("article %d marked as read", article_id)


def _render_article(article: Article, source_title: str) -> str:
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

    body = _format_content(article.content, article.summary)

    return (
        '<html><body style="font-family: -apple-system, system-ui, sans-serif; padding: 16px;">'
        f'<h1 style="margin-bottom: 4px;">{title}</h1>'
        f'<p style="color: #6b7280; margin-top: 0;">{meta_line}</p>'
        "<hr>"
        f"{body}"
        "</body></html>"
    )


def _format_when(when: datetime | None) -> str:
    if when is None:
        return ""
    return when.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_content(content: str | None, summary: str | None) -> str:
    raw = (content or summary or "").strip()
    if not raw:
        return '<p style="color: #6b7280;"><em>(Kein Inhalt extrahiert.)</em></p>'

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
