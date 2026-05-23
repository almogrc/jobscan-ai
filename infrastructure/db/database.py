"""
infrastructure/db/database.py

The DB file is always at:
    <project_root>/infrastructure/db/jobs.db

This is resolved using THIS file's own __file__ path, so it is correct
regardless of which directory you run scripts from. Every script that
imports SessionLocal or engine will hit the exact same file.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Resolve to the directory containing THIS file — always infrastructure/db/
# regardless of cwd.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(_THIS_DIR, "jobs.db")

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()