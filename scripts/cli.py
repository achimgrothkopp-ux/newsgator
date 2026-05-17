"""Small CLI to populate, inspect and sync the real Newsgator DB.

Usage examples (run from the project root with the venv active):

    .venv/bin/python -m scripts.cli seed
    .venv/bin/python -m scripts.cli add rss https://www.heise.de/rss/heise-atom.xml --category Tech
    .venv/bin/python -m scripts.cli add youtube https://www.youtube.com/@veritasium --category Wissenschaft
    .venv/bin/python -m scripts.cli list
    .venv/bin/python -m scripts.cli sync
    .venv/bin/python -m scripts.cli remove 3

All commands target the same on-disk DB the GUI uses
(``~/.local/share/newsgator/newsgator.db``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import delete, select
from sqlalchemy.sql import exists as sql_exists

from newsgator.models.article import Article
from newsgator.models.database import get_session_factory, init_db
from newsgator.models.source import Source
from newsgator.sync.scheduler import PROVIDERS, FeedScheduler

FEED_TYPES = sorted(PROVIDERS.keys())

DEFAULT_SOURCES: list[tuple[str, str, str, str | None]] = [
    ("rss",     "Heise News",   "https://www.heise.de/rss/heise-atom.xml",          "Tech"),
    ("rss",     "Golem",        "https://rss.golem.de/rss.php?feed=ATOM1.0",        "Tech"),
    ("rss",     "Tagesschau",   "https://www.tagesschau.de/index~rss2.xml",         "Nachrichten"),
    ("youtube", "Veritasium",   "https://www.youtube.com/@veritasium",              "Wissenschaft"),
    ("youtube", "3Blue1Brown",  "https://www.youtube.com/@3blue1brown",             "Wissenschaft"),
    ("http",    "uv Docs",      "https://docs.astral.sh/uv/getting-started/installation/", None),
]


# ---------- commands ------------------------------------------------------


async def cmd_add(args: argparse.Namespace) -> int:
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        exists = await session.scalar(select(Source).where(Source.url == args.url))
        if exists:
            print(f"skipped: source already exists with id {exists.id}: {args.url}")
            return 0
        title = args.title or args.url
        src = Source(
            url=args.url, title=title, feed_type=args.feed_type, category=args.category
        )
        session.add(src)
        await session.commit()
        await session.refresh(src)
        print(f"added: id={src.id} [{src.feed_type}] {src.title}")
    return 0


async def cmd_list(_: argparse.Namespace) -> int:
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        sources = (
            await session.execute(
                select(Source).order_by(
                    Source.category.is_(None),
                    Source.category.asc(),
                    Source.title.asc(),
                )
            )
        ).scalars().all()

        if not sources:
            print("(no sources yet — try `seed` or `add`)")
            return 0

        for s in sources:
            count = await session.scalar(
                select(__import__("sqlalchemy").func.count())
                .select_from(Article)
                .where(Article.source_id == s.id)
            )
            cat = s.category or "—"
            last = s.last_synced.astimezone().strftime("%Y-%m-%d %H:%M") if s.last_synced else "—"
            print(f"  #{s.id:<3} [{s.feed_type:<7}] {s.title:<24} cat={cat:<14} articles={count:<4} last_sync={last}")
    return 0


async def cmd_remove(args: argparse.Namespace) -> int:
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        src = await session.get(Source, args.id)
        if src is None:
            print(f"no source with id {args.id}")
            return 1
        print(f"removing #{src.id} [{src.feed_type}] {src.title}")
        # session.delete triggers the relationship cascade; combined with the
        # DB-level ON DELETE CASCADE (now active via PRAGMA foreign_keys=ON)
        # it's belt-and-braces against orphaned articles.
        await session.delete(src)
        await session.commit()
    return 0


async def cmd_cleanup(_: argparse.Namespace) -> int:
    """Delete articles whose source no longer exists.

    One-time fix for DBs that were touched before PRAGMA foreign_keys was
    enabled — the original ``remove`` bypassed cascade so orphans accumulated,
    and SQLite reusing primary-key rowids then attached them to whatever
    source landed on the same id next.
    """
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        stmt = delete(Article).where(
            ~sql_exists().where(Source.id == Article.source_id)
        )
        result = await session.execute(stmt)
        await session.commit()
        print(f"removed {result.rowcount} orphan article(s)")
    return 0


async def cmd_sync(_: argparse.Namespace) -> int:
    await init_db()
    factory = get_session_factory()
    scheduler = FeedScheduler(factory)
    results = await scheduler.sync_all()
    if not results:
        print("(no sources to sync)")
        return 0
    print(f"{'#':>3}  {'type':<8} {'new':>5}  status   url")
    print(f"{'-'*3:>3}  {'-'*8:<8} {'-'*5:>5}  -------  {'-'*60}")
    for r in results:
        status = "ok" if r.ok else "ERROR"
        note = f" — {r.error}" if r.error else ""
        print(f"{r.source_id:>3}  {r.feed_type:<8} {r.new_articles:>5}  {status:<7}  {r.source_url}{note}")
    total_new = sum(r.new_articles for r in results)
    ok_count = sum(1 for r in results if r.ok)
    print(f"\n{ok_count}/{len(results)} sources ok, {total_new} new articles")
    return 0


async def cmd_seed(_: argparse.Namespace) -> int:
    await init_db()
    factory = get_session_factory()
    added = 0
    async with factory() as session:
        for feed_type, title, url, category in DEFAULT_SOURCES:
            exists = await session.scalar(select(Source).where(Source.url == url))
            if exists:
                print(f"skip  #{exists.id} [{feed_type:<7}] {title}")
                continue
            session.add(Source(url=url, title=title, feed_type=feed_type, category=category))
            added += 1
            print(f"add        [{feed_type:<7}] {title}")
        if added:
            await session.commit()
    print(f"\n{added} new source(s) added")
    return 0


# ---------- entry point ---------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a new source")
    p_add.add_argument("feed_type", choices=FEED_TYPES)
    p_add.add_argument("url")
    p_add.add_argument("--title", help="display name (defaults to URL)")
    p_add.add_argument("--category", help="optional category for grouping")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="show all sources with article counts")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove", help="delete a source (and its articles)")
    p_rm.add_argument("id", type=int)
    p_rm.set_defaults(func=cmd_remove)

    p_sync = sub.add_parser("sync", help="fetch all sources once and store new articles")
    p_sync.set_defaults(func=cmd_sync)

    p_seed = sub.add_parser("seed", help="add a curated starter set (idempotent)")
    p_seed.set_defaults(func=cmd_seed)

    p_clean = sub.add_parser(
        "cleanup",
        help="delete articles whose source no longer exists (one-time DB fix)",
    )
    p_clean.set_defaults(func=cmd_cleanup)

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
