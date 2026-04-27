"""
clean_db.py — Emergency utility: wipes all rows from the `jobs` table.
Place this file at the project root and run it directly:

    python clean_db.py

The table structure is preserved (no DROP TABLE).
Safe to run at any time — it is fully idempotent.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Path bootstrap
#
# WHY THIS IS NEEDED:
# database.py resolves its SQLite file path using its OWN __file__ location:
#   current_dir = os.path.dirname(os.path.abspath(__file__))  # → .../infrastructure/db/
#
# The relative package imports inside db/ (.database, .model) require that
# the project root is on sys.path so Python can resolve `infrastructure.db`
# as a package. Without this, you get "attempted relative import beyond
# top-level package" when running from the root.
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.insert(0, project_root)
from infrastructure.db.database import SessionLocal
from infrastructure.db.model import Job

def clean_jobs_table() -> None:
    db = SessionLocal()
    try:
        # Query the count first for the print statement, then bulk-delete.
        #
        # WHY db.query(Job).delete() INSTEAD OF SELECT + loop?
        # SQLAlchemy's bulk delete issues a single DELETE FROM jobs WHERE ...
        # statement — one round-trip regardless of row count. Looping over
        # objects and calling db.delete(obj) is O(n) round-trips and loads
        # every row into memory first. For an emergency cleanup you want
        # it fast and simple.
        #
        # synchronize_session=False tells SQLAlchemy not to try to update
        # its in-memory session cache after the delete — correct here because
        # we're not using those objects again in this session.
        deleted = db.query(Job).delete(synchronize_session=False)
        db.commit()
        print(f"[clean_db] Done. {deleted} row(s) deleted from `jobs`.")
    except Exception as e:
        db.rollback()
        print(f"[clean_db] ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("[clean_db] Wiping all jobs from the database...")
    clean_jobs_table()