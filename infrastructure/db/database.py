"""
infrastructure/db/database.py

Local default: a SQLite file at <project_root>/infrastructure/db/jobs.db,
resolved from THIS file's own __file__ path, so every script hits the same
file no matter which directory you run it from.

Cloud: set DATABASE_URL and the same code talks to Postgres, e.g.
    postgresql+psycopg2://USER:PASSWORD@/jobscan?host=/cloudsql/PROJECT:REGION:INSTANCE
A SQLite file can't live on Cloud Run: the disk is wiped on every deploy and
each instance would get its own copy.
"""

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(_THIS_DIR, "jobs.db")

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH}"
IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        # timeout: wait up to 30s for a write lock instead of failing at once.
        # The Pub/Sub client runs several callbacks at the same time.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_wal(dbapi_connection, _record):
        # WAL lets readers (the SQLite viewer, the matcher) work while a worker writes.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
