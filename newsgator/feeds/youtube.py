"""YouTube channel and playlist provider.

Uses YouTube's public RSS feeds (no API key needed):

    https://www.youtube.com/feeds/videos.xml?channel_id=UCxxxxxxxxxxxxxxxxxxxxxx
    https://www.youtube.com/feeds/videos.xml?playlist_id=PLxxxxxxxxxxxxxxxx

Accepts several input URL formats from the user — the actual feed URL is
resolved on each fetch:

- Direct RSS URL (``/feeds/videos.xml?...``)             — used as-is.
- Playlist URL (any URL with ``?list=PL...``, including
  a ``/watch?v=...&list=...`` link from inside a playlist) — mapped to
                                                             ``playlist_id``
                                                             RSS endpoint.
- Channel URL (``/channel/UCxxx``)                       — channel_id is in the path.
- Handle URL (``/@handle``) or legacy ``/c/...`` /
  ``/user/...``                                          — fetch the HTML
                                                           page and grep for
                                                           the canonical
                                                           ``channelId``.

Why playlists matter: many channels publish short topic-clips of long
podcasts/videos as separate uploads. The channel feed mixes both. A curated
playlist (e.g. "Lex Fridman Podcast") usually contains only the full
episodes, so subscribing to the playlist gives the cleaner stream.
"""

from __future__ import annotations

import logging
import re
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import httpx

from newsgator.feeds.base import FetchedArticle
from newsgator.feeds.rss import RssFeedProvider, USER_AGENT
from newsgator.models.source import Source

logger = logging.getLogger(__name__)

CHANNEL_FEED_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
PLAYLIST_FEED_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?playlist_id={pid}"
CHANNEL_PATH_RE = re.compile(r"/channel/(UC[A-Za-z0-9_-]{22})")
CHANNEL_ID_IN_HTML_RE = re.compile(r'"channelId":"(UC[A-Za-z0-9_-]{22})"')
# Playlist IDs start with two letters then a long suffix; PL/UU/LL/FL/OL/RD are common.
PLAYLIST_ID_RE = re.compile(r"^[A-Z]{2}[A-Za-z0-9_-]{10,}$")


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

    # 2. Any URL carrying a ``list=`` query param — playlist takes priority
    #    over channel detection (a /watch URL with both v= and list= is more
    #    likely meant as a playlist subscription).
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    list_values = query.get("list", [])
    if list_values:
        playlist_id = list_values[0]
        if PLAYLIST_ID_RE.match(playlist_id):
            return PLAYLIST_FEED_TEMPLATE.format(pid=playlist_id)
        logger.warning("YouTube: ignoring unrecognised playlist id %r", playlist_id)

    # 3. /channel/UCxxx — channel_id is right there in the path.
    match = CHANNEL_PATH_RE.search(url)
    if match:
        return CHANNEL_FEED_TEMPLATE.format(cid=match.group(1))

    # 4. /@handle, /c/name, /user/name — fetch and grep for the canonical id.
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
        return CHANNEL_FEED_TEMPLATE.format(cid=match.group(1))

    return None
