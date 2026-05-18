"""QTextBrowser subclass that fetches external <img> resources.

Vanilla QTextBrowser only resolves local resources; remote ``<img src="https://…">``
tags render as empty boxes. We override ``loadResource`` to serve from an
in-memory cache, kick off async fetches for missing images, and re-set the HTML
once they arrive so the layout picks them up.

Scroll position is preserved across the re-set, and a per-load generation
counter discards results that belong to a previously open article.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser, QWidget

logger = logging.getLogger(__name__)

IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
FETCH_TIMEOUT = 10.0
USER_AGENT = "newsgator/0.1 (+https://github.com/achimgrothkopp-ux/newsgator)"


class ImageTextBrowser(QTextBrowser):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_cache: dict[str, QImage] = {}
        self._load_gen: int = 0
        self._fetch_task: asyncio.Task[None] | None = None

    def set_article_html(self, html: str) -> None:
        """setHtml + background image loading. Use this instead of setHtml
        for article bodies; placeholder/about screens can stay on plain setHtml."""
        self._load_gen += 1
        self.setHtml(html)

        urls = _collect_remote_img_urls(html)
        missing = [u for u in urls if u not in self._image_cache]
        if not missing:
            return

        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
        gen = self._load_gen
        self._fetch_task = asyncio.create_task(self._load_images(missing, gen, html))

    # Qt override -------------------------------------------------------

    def loadResource(self, type_: int, name: QUrl):  # noqa: N802 - Qt API
        if type_ == int(QTextDocument.ResourceType.ImageResource):
            image = self._image_cache.get(name.toString())
            if image is not None:
                return self._fit_to_viewport(image)
        return super().loadResource(type_, name)

    def _fit_to_viewport(self, image: QImage) -> QImage:
        # Leave a small gutter so the right edge of the image doesn't kiss
        # the scrollbar; matches the 16px body padding from _render_article.
        max_width = max(64, self.viewport().width() - 40)
        if image.width() <= max_width:
            return image
        return image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)

    # Internal ----------------------------------------------------------

    async def _load_images(self, urls: list[str], gen: int, html: str) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                results = await asyncio.gather(
                    *(self._fetch_one(client, u) for u in urls),
                    return_exceptions=False,
                )
        except asyncio.CancelledError:
            raise

        if gen != self._load_gen:
            # User opened a different article meanwhile; results would re-layout
            # the wrong document.
            return

        loaded_any = False
        for url, payload in zip(urls, results):
            if payload is None:
                continue
            image = QImage()
            if not image.loadFromData(payload):
                continue
            self._image_cache[url] = image
            loaded_any = True

        if not loaded_any:
            return

        scroll = self.verticalScrollBar().value()
        self.setHtml(html)
        self.verticalScrollBar().setValue(scroll)

    async def _fetch_one(self, client: httpx.AsyncClient, url: str) -> bytes | None:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("img fetch failed: %s — %s", url, exc)
            return None
        return response.content


def _collect_remote_img_urls(html: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in IMG_SRC_RE.finditer(html):
        url = match.group(1).strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered
