"""
infrastructure/db/sync_plan.py — decides what one scrape run changes in the DB.

Pure Python: no SQLAlchemy, no I/O. process_scraped_site() in db_operations.py
loads the site's current rows, asks plan_sync() what to do, and applies the
plan in ONE transaction. Keeping the decisions here means they can be unit
tested without a database.

Rules:
  1. A job is identified by (site_id, job_hash) — the ATS's own id — NOT by
     URL. Some companies point every Comeet position at one generic careers
     page, so keying on URL collapsed all their jobs into one row.
  2. Changed title / location / description / url are written back, and
     content_hash changes so the matcher knows to re-score that job.
     An empty description never overwrites a stored one (a failed detail
     fetch must not wipe good data).
  3. Jobs missing from the scrape are CLOSED (closed_at set), not deleted, so
     applications that point at them keep their history. A job that shows up
     again is reopened.
  4. Circuit breaker: scrapers return [] or a short list when an API hiccups.
     If a scrape returns less than MIN_HEALTHY_SHARE of the jobs we think are
     open, nothing is closed for being missing. Jobs not seen for STALE_AFTER
     are closed anyway, so a company that really stopped hiring (or a scraper
     that stays broken) doesn't keep "open" jobs forever.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

MIN_HEALTHY_SHARE = 0.5          # scrape must return >= 50% of currently open jobs
SMALL_SITE        = 5            # below this many open jobs the share rule is skipped
STALE_AFTER       = timedelta(days=7)


@dataclass
class ExistingJob:
    """The fields of a stored Job row that the planner needs."""
    id:           int
    job_hash:     str
    url:          str = ""
    title:        str = ""
    location:     str = ""
    description:  str = ""
    content_hash: str = ""
    last_seen:    datetime | None = None
    closed_at:    datetime | None = None


@dataclass
class SyncPlan:
    inserts:    list[dict]                 = field(default_factory=list)  # normalized new jobs
    updates:    list[tuple[int, dict]]     = field(default_factory=list)  # (row id, {field: new value})
    seen_ids:   list[int]                  = field(default_factory=list)  # stamp last_seen
    reopen_ids: list[int]                  = field(default_factory=list)  # closed rows that came back
    close_ids:  list[int]                  = field(default_factory=list)  # open rows to close
    skipped:    int  = 0                   # scraped items without a title or url
    healthy:    bool = True                # False -> missing jobs were not closed
    note:       str  = ""

    @property
    def scraped_count(self) -> int:
        return len(self.inserts) + len(self.seen_ids)


def content_hash(title: str, location: str, description: str) -> str:
    raw = "\n".join((title or "", location or "", description or ""))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def job_key(job_hash: str, url: str) -> str:
    """The ATS id when the scraper has one, otherwise a stable id derived from the URL."""
    job_hash = (job_hash or "").strip()
    if job_hash:
        return job_hash
    return "url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def normalize(job: dict) -> dict | None:
    """Clean one scraper dict. Returns None if it has no title or no url."""
    url   = (job.get("url") or "").strip()
    title = (job.get("title") or "").strip()
    if not url or not title:
        return None
    location    = (job.get("location") or "").strip()
    description = (job.get("description") or "").strip()
    return {
        "job_hash":     job_key(str(job.get("job_hash") or ""), url),
        "title":        title,
        "url":          url,
        "location":     location,
        "description":  description,
        "content_hash": content_hash(title, location, description),
    }


def _utc(value: datetime) -> datetime:
    # SQLite hands datetimes back without tzinfo; we always store UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def plan_sync(existing: list[ExistingJob], scraped: list[dict], now: datetime) -> SyncPlan:
    """Compare one site's stored jobs with a fresh scrape of that site."""
    now  = _utc(now)
    plan = SyncPlan()

    incoming: dict[str, dict] = {}
    for raw in scraped:
        job = normalize(raw)
        if job is None:
            plan.skipped += 1
            continue
        incoming[job["job_hash"]] = job          # same id twice in one response -> last wins

    stored = {row.job_hash: row for row in existing}

    for key, job in incoming.items():
        row = stored.get(key)
        if row is None:
            plan.inserts.append(job)
            continue

        plan.seen_ids.append(row.id)
        if row.closed_at is not None:
            plan.reopen_ids.append(row.id)

        description = job["description"] or row.description   # never wipe a stored description
        new_values = {
            "title":       job["title"],
            "url":         job["url"],
            "location":    job["location"],
            "description": description,
        }
        changes = {k: v for k, v in new_values.items() if v != (getattr(row, k) or "")}
        new_hash = content_hash(job["title"], job["location"], description)
        if new_hash != row.content_hash:
            changes["content_hash"] = new_hash
        if changes:
            plan.updates.append((row.id, changes))

    open_rows = [row for row in existing if row.closed_at is None]
    missing   = [row for row in open_rows if row.job_hash not in incoming]

    if not incoming:
        plan.healthy = not open_rows             # an empty scrape of a site with open jobs is never trusted
    elif len(open_rows) < SMALL_SITE:
        plan.healthy = True
    else:
        plan.healthy = len(incoming) >= MIN_HEALTHY_SHARE * len(open_rows)

    for row in missing:
        too_old = row.last_seen is not None and now - _utc(row.last_seen) >= STALE_AFTER
        if plan.healthy or too_old:
            plan.close_ids.append(row.id)

    if not plan.healthy:
        plan.note = (
            f"partial scrape: got {len(incoming)} job(s) but {len(open_rows)} are open; "
            f"kept {len(missing) - len(plan.close_ids)} missing job(s) open"
        )
    return plan
