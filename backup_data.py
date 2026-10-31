"""MarketPulse Phase 12: keep dated copies of the database.

Run with:  python backup_data.py

SQLite's backup call copies a consistent database even while the API is using it. A
plain file copy could catch a half-finished write. Copies stay on this disk, so keep
one somewhere else too.
"""

import sqlite3
import sys
from contextlib import closing
from datetime import datetime

import database

BACKUP_FOLDER = "backups"
KEEP_COPIES = 14


def back_up(now=None):
    """Copy the database, delete the oldest extra copies, and return the new path."""
    source = database.DATA_FOLDER / database.DATABASE_FILE
    # Connecting would create an empty database, which is not worth a backup.
    if not source.exists():
        return None

    folder = database.DATA_FOLDER / BACKUP_FOLDER
    folder.mkdir(exist_ok=True)
    target = folder / f"marketpulse-{now or datetime.now():%Y%m%d-%H%M%S}.db"

    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(target)) as copy:
        original.backup(copy)
        result = copy.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        target.unlink()
        raise RuntimeError(f"Backup failed its integrity check: {result}")

    for old in sorted(folder.glob("marketpulse-*.db"))[:-KEEP_COPIES]:
        old.unlink()
    return target


def main():
    target = back_up()
    print(f"Backed up to {target}" if target else "No database yet, so nothing to back up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
