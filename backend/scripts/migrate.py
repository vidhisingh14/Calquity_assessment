"""Apply numbered SQL migrations in order. Idempotent.

Plain SQL files, applied in filename order, tracked in schema_migrations. No
ORM, no autogeneration -- the schema should be readable by anyone reviewing the
repo without running anything.
"""

from __future__ import annotations

import pathlib
import sys

from app.repositories.db import connection

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


def applied_migrations(conn) -> set[str]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          filename   TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {r["filename"] for r in rows}


def main() -> int:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"No migrations found in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    with connection() as conn:
        done = applied_migrations(conn)
        for path in files:
            if path.name in done:
                print(f"  skip  {path.name}")
                continue
            print(f"  apply {path.name}")
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
            )
        conn.commit()

    print(f"migrations up to date ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
