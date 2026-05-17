"""Smoke test: create all tables in a temp SQLite DB and dump the schema."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path

from newsgator.models.database import dispose_engine, init_db


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "smoke.db"
        await init_db(db)
        await dispose_engine()

        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
        finally:
            conn.close()

        for type_, name, sql in rows:
            print(f"-- {type_}: {name}")
            print((sql or "").rstrip(), end=";\n\n")


if __name__ == "__main__":
    asyncio.run(main())
