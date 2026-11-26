"""
reset_db.py — Hard-reset the database: delete jobs.db and recreate schema.

Run from the project root:
    python reset_db.py

What this does:
  1. Resolves the exact DB file path from infrastructure/db/database.py
     (same path every other script uses — guaranteed to be the same file)
  2. Deletes jobs.db if it exists
  3. Calls Base.metadata.create_all() to recreate all tables from scratch
     including every column currently defined in model.py
     (description, location, job_hash, etc.)
  4. Prints a confirmation with the absolute path so you can verify

WARNING: This permanently deletes all job data. Run seed scripts after.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

# Import in this order — database first (defines engine + Base),
# then model (registers table definitions against Base).
# create_all() only knows about tables that have been imported.
from infrastructure.db.database import engine, DB_PATH, IS_SQLITE   # noqa: E402
from infrastructure.db import model                       # noqa: E402, F401  ← registers models


def reset() -> None:
    if not IS_SQLITE:
        raise SystemExit("[reset_db] DATABASE_URL points at a server database. "
                         "This script only resets the local SQLite file; unset DATABASE_URL first.")
    print(f"[reset_db] Target file: {DB_PATH}")

    # Step 1 — delete existing file, plus the WAL sidecar files SQLite keeps
    # next to it (a leftover jobs.db-wal must not be replayed into a new DB)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[reset_db] Deleted existing jobs.db")
    else:
        print(f"[reset_db] No existing jobs.db found — creating fresh.")
    for suffix in ("-wal", "-shm"):
        if os.path.exists(DB_PATH + suffix):
            os.remove(DB_PATH + suffix)

    # Step 2 — recreate all tables from current model definitions
    # model.py was imported above, so Base.metadata knows about Job + TargetSite
    # including the new `description` and `location` columns.
    from infrastructure.db.database import Base
    Base.metadata.create_all(bind=engine)

    print(f"[reset_db] ✅ Schema created. Tables:")
    for table_name in Base.metadata.tables:
        cols = [c.name for c in Base.metadata.tables[table_name].columns]
        print(f"   {table_name}: {cols}")


if __name__ == "__main__":
    reset()