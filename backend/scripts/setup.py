"""`docker compose run --rm setup` -> migrate, then ingest, in one command.

This is the path a reviewer follows. It must work from a clean clone with
nothing installed on the host but Docker.
"""

from __future__ import annotations

import sys

from scripts import migrate


def main() -> int:
    print("== migrations ==")
    rc = migrate.main()
    if rc != 0:
        return rc

    print("\n== ingestion ==")
    from ingestion import run_ingest

    return run_ingest.main()


if __name__ == "__main__":
    sys.exit(main())
