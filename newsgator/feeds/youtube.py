"""YouTube channel provider.

Uses YouTube's public RSS feed (no API key needed):

    https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxxxxxxxxxxxxxxxxxxx

Accepts several input URL formats from the user — the actual feed URL is
resolved on each fetch:

- Direct RSS URL (``/feeds/videos.xml?channel_id=...``) — used as-is.
- Channel URL (``/channel/UCxxx``)                       — channel_id is in the path.
- Handle URL (``/@handle``) or legacy ``/c/...`` /
  ``/user/...``                                          — fetch the HTML
                                                           page and grep for
                                                           the canonical
                                                           ``channelId``.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar

import httpx

from newsgator.feeds.base import FetchedArticle
from newsgator.feeds.rss import RssFeedProvider, USER_AGENT
from newsgator.models.source import Source

logger = logging.getLogger(__name__)

RSS_FEED_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
CHANNEL_PATH_RE = re.compile(r"/channel/(UC[A-Za-z0-9_-]{22})")
CHANNEL_ID_IN_HTML_RE = re.compile(r'"channelId":"(UC[A-Za-z0-9_-]{22})"')


class YoutubeFeedProvider(RssFeedProvider):
    feed_type: ClassVar[str] = "youtube"

    async def fetch(
        self, source: Source, client: httpx.AsyncClient
    ) -> list[FetchedArticle]:
        feed_url = await _resolve_feed_url(source.url, client)
        if not feed_url:
            logger.warning("YouTube: could not resolve channel feed for %s", source.url)
            return []
        return await self._fetch_from_url(feed_url, client)


async def _resolve_feed_url(url: str, client: httpx.AsyncClient) -> str | None:
    # 1. Already the canonical RSS endpoint.
    if "/feeds/videos.xml" in url:
        return url

    # 2. /channel/UCxxx — channel_id is right there in the path.
    match = CHANNEL_PATH_RE.search(url)
    if match:
        return RSS_FEED_TEMPLATE.format(cid=match.group(1))

    # 3. /@handle, /c/name, /user/name — fetch and grep for the canonical id.
    #    From EU IPs YouTube redirects to consent.youtube.com; the ``CONSENT``
    #    cookie below bypasses that gate so we get the real channel page.
    try:
        response = await client.get(
            url,
            headers={"User-Agent": USER_AGENT},
            cookies={"CONSENT": "YES+1", "SOCS": "CAI"},
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("YouTube channel page fetch failed for %s: %s", url, exc)
        return None

    match = CHANNEL_ID_IN_HTML_RE.search(response.text)
    if match:
        return RSS_FEED_TEMPLATE.format(cid=match.group(1))

    return None
