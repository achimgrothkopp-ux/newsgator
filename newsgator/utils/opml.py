"""OPML 2.0 import/export for feed subscriptions.

OPML is the de-facto exchange format for feed readers. We treat each
``<outline>`` with an ``xmlUrl`` attribute as a feed source and nested
``<outline>`` containers (without ``xmlUrl``) as categories.

Newsgator supports three feed types — ``rss``, ``http`` and ``youtube``.
On export we write that into the ``type`` attribute; on import we trust it
when present and fall back to ``rss`` otherwise (the OPML default).
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass(slots=True, frozen=True)
class OpmlEntry:
    feed_type: str
    url: str
    title: str
    category: str | None


_KNOWN_TYPES = {"rss", "http", "youtube"}


def parse_opml(xml_text: str) -> list[OpmlEntry]:
    """Return every feed outline found in ``xml_text``.

    Categories come from the title/text of the parent ``<outline>``.
    Malformed entries (no URL) are silently skipped.
    """
    root = ET.fromstring(xml_text)
    body = root.find("body")
    if body is None:
        return []
    return list(_walk(body, category=None))


def _walk(node: ET.Element, category: str | None):
    for child in node.findall("outline"):
        url = child.get("xmlUrl") or child.get("htmlUrl") or ""
        if url:
            feed_type = (child.get("type") or "rss").lower()
            if feed_type not in _KNOWN_TYPES:
                feed_type = "rss"
            title = child.get("title") or child.get("text") or url
            yield OpmlEntry(
                feed_type=feed_type,
                url=url,
                title=title,
                category=category,
            )
        else:
            # Category container — recurse with this outline's label as the
            # new category for the children inside.
            label = child.get("title") or child.get("text") or ""
            sub_category = label.strip() or category
            yield from _walk(child, category=sub_category)


def build_opml(entries: list[OpmlEntry], *, title: str = "Newsgator Subscriptions") -> str:
    """Serialize ``entries`` as OPML 2.0 grouped by category."""
    root = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = title
    body = ET.SubElement(root, "body")

    by_category: dict[str | None, list[OpmlEntry]] = {}
    for entry in entries:
        by_category.setdefault(entry.category, []).append(entry)

    # Categorized first (alphabetically), uncategorized at the bottom.
    sorted_cats = sorted(
        by_category.keys(),
        key=lambda c: (c is None, (c or "").lower()),
    )
    for cat in sorted_cats:
        items = by_category[cat]
        if cat is None:
            parent = body
        else:
            parent = ET.SubElement(body, "outline", {"title": cat, "text": cat})
        for entry in items:
            ET.SubElement(
                parent,
                "outline",
                {
                    "type": entry.feed_type,
                    "title": entry.title,
                    "text": entry.title,
                    "xmlUrl": entry.url,
                },
            )

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )
