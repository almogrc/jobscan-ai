"""
End-to-end tests for process_scraped_site() on a throwaway SQLite file
(conftest.py points DATABASE_URL at it). Skipped when SQLAlchemy isn't installed.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402

from infrastructure.db import db_operations  # noqa: E402
from infrastructure.db.database import Base, SessionLocal, engine  # noqa: E402
from infrastructure.db.model import Job, TargetSite  # noqa: E402

T0 = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def site_id():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    site = TargetSite(name="comeet", company="OurCrowd", base_url="D3.00A|TOKEN")
    db.add(site)
    db.commit()
    site_id = site.id
    db.close()
    return site_id


def _jobs(*ids, url=None, description="Python"):
    return [{"job_hash": i, "title": f"Job {i}", "url": url or f"https://x/{i}",
             "location": "Tel Aviv", "description": description} for i in ids]


def _rows(site_id):
    db = SessionLocal()
    try:
        return {r.job_hash: (r.closed_at is None, r.description) for r in db.query(Job).filter_by(site_id=site_id)}
    finally:
        db.close()


def test_shared_url_jobs_are_all_stored(site_id):
    db_operations.process_scraped_site(site_id, _jobs("a", "b", "c", url="https://www.ourcrowd.com/careers"), T0.isoformat())
    assert set(_rows(site_id)) == {"a", "b", "c"}


def test_close_reopen_and_site_status(site_id):
    db_operations.process_scraped_site(site_id, _jobs("a", "b", "c"), T0.isoformat())
    db_operations.process_scraped_site(site_id, _jobs("a", "b"), (T0 + timedelta(hours=6)).isoformat())
    assert _rows(site_id)["c"][0] is False                       # closed, row kept

    db_operations.process_scraped_site(site_id, _jobs("a", "b", "c"), (T0 + timedelta(hours=12)).isoformat())
    assert _rows(site_id)["c"][0] is True                        # reopened

    db = SessionLocal()
    site = db.get(TargetSite, site_id)
    assert (site.last_status, site.last_count) == ("ok", 3)
    db.close()


def test_partial_scrape_keeps_jobs_open(site_id):
    db_operations.process_scraped_site(site_id, _jobs(*"abcdefghij"), T0.isoformat())
    plan = db_operations.process_scraped_site(site_id, _jobs("a"), (T0 + timedelta(hours=6)).isoformat())
    assert not plan.healthy
    assert all(is_open for is_open, _ in _rows(site_id).values())


def test_db_errors_propagate_and_roll_back(site_id, monkeypatch):
    db_operations.process_scraped_site(site_id, _jobs("a"), T0.isoformat())

    def broken_plan(*args, **kwargs):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(db_operations, "plan_sync", broken_plan)
    with pytest.raises(RuntimeError):                      # the old code swallowed this
        db_operations.process_scraped_site(site_id, _jobs("a", "b"), T0.isoformat())
    assert set(_rows(site_id)) == {"a"}


def test_ensure_schema_builds_an_empty_database(tmp_path, monkeypatch):
    fresh = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(db_operations, "engine", fresh)
    db_operations.ensure_schema()
    with fresh.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"jobs", "target_sites"} <= tables


def test_ensure_schema_flags_the_old_jobs_db(tmp_path, monkeypatch):
    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE target_sites (id INTEGER PRIMARY KEY, name VARCHAR, base_url VARCHAR, is_active BOOLEAN)"))
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title VARCHAR, site_id INTEGER, url VARCHAR UNIQUE, "
                          "job_hash VARCHAR, location VARCHAR, description TEXT, created_at DATETIME, last_seen DATETIME)"))
    monkeypatch.setattr(db_operations, "engine", old)
    with pytest.raises(db_operations.SchemaOutOfDate):
        db_operations.ensure_schema()
