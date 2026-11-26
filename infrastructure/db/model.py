"""
infrastructure/db/model.py

target_sites — one row per company source. `name` picks the scraper
               (comeet / greenhouse / lever / checkpoint / amazon),
               `company` is the display name ("Monday.com").
jobs         — one row per posting, identified by (site_id, job_hash),
               where job_hash is the ATS's own id. Closed postings keep
               their row (closed_at is set) so history isn't lost.

Schema changed in fix/cloud-ready: run `python reset_db.py` and then
`python seed_comeet_discovery.py` once to rebuild a local jobs.db.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("site_id", "job_hash", name="uq_jobs_site_job"),)

    id           = Column(Integer, primary_key=True, index=True)
    site_id      = Column(Integer, ForeignKey("target_sites.id"), nullable=False, index=True)
    job_hash     = Column(String, nullable=False)        # ATS id: Comeet uid, Greenhouse id, Lever id ...
    title        = Column(String)
    url          = Column(String, index=True)            # NOT unique: some companies reuse one careers URL
    location     = Column(String, default="")
    description  = Column(Text, default="")
    content_hash = Column(String(40), default="")        # sha1(title, location, description) -> spot edits
    created_at   = Column(DateTime(timezone=True), default=_utcnow)
    updated_at   = Column(DateTime(timezone=True), default=_utcnow)   # last time the content changed
    last_seen    = Column(DateTime(timezone=True), default=_utcnow)
    closed_at    = Column(DateTime(timezone=True), nullable=True, index=True)  # None = still open


class TargetSite(Base):
    __tablename__ = "target_sites"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String)                          # scraper key
    company     = Column(String, default="")              # display name
    base_url    = Column(String, unique=True)
    is_active   = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String, default="")              # ok / empty / error
    last_count  = Column(Integer, default=0)
    last_error  = Column(Text, default="")
