"""
run_scan.py — scan every active company once, then exit.

This is what the GitHub Actions workflow (.github/workflows/scan.yml) runs twice a
day. It uses the same scrapers and the same DB code as worker.py, just without
Pub/Sub: up to SCAN_CONCURRENCY companies are scraped at the same time in one
process, then the results are written to the database one company at a time
(SQLite allows one writer).

Run it yourself from the project root:
    python run_scan.py

Afterwards it writes jobs.csv (open jobs only, no descriptions) next to jobs.db,
so the list can be read on GitHub, even from a phone.
"""

import asyncio
import csv
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
for path in (ROOT, os.path.join(ROOT, "services", "discovery-agent")):
    if path not in sys.path:
        sys.path.insert(0, path)

from scrapers.amazon import scrape_amazon            # noqa: E402
from scrapers.checkpoint import scrape_checkpoint    # noqa: E402
from scrapers.comeet import scrape_comeet            # noqa: E402
from scrapers.greenhouse import scrape_greenhouse    # noqa: E402
from scrapers.lever import scrape_lever              # noqa: E402

SCRAPERS = {
    "comeet":     scrape_comeet,
    "greenhouse": scrape_greenhouse,
    "lever":      scrape_lever,
    "checkpoint": scrape_checkpoint,
    "amazon":     scrape_amazon,
}

SITE_TIMEOUT = 300      # seconds; one stuck site must not hold the whole run


async def scan_site(site: dict, semaphore: asyncio.Semaphore, scrapers: dict) -> tuple[dict, list | None, str]:
    """Returns (site, jobs, error). jobs is None when the site failed."""
    scraper = scrapers.get((site.get("name") or "").lower().strip())
    if scraper is None:
        return site, None, f"no scraper called '{site.get('name')}'"
    async with semaphore:
        try:
            jobs = await asyncio.wait_for(scraper(site["url"]), timeout=SITE_TIMEOUT)
            return site, list(jobs or []), ""
        except Exception as e:
            return site, None, f"{type(e).__name__}: {e}"


async def scan_all(sites: list[dict], scrapers: dict = SCRAPERS, concurrency: int = 4) -> list[tuple[dict, list | None, str]]:
    semaphore = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(scan_site(site, semaphore, scrapers) for site in sites))


def export_open_jobs_csv(path: str) -> int:
    from infrastructure.db.database import SessionLocal
    from infrastructure.db.model import Job, TargetSite

    db = SessionLocal()
    try:
        rows = (
            db.query(Job, TargetSite)
            .join(TargetSite, Job.site_id == TargetSite.id)
            .filter(Job.closed_at.is_(None))
            .order_by(TargetSite.company, Job.title)
            .all()
        )
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["company", "title", "location", "first_seen", "url"])
            for job, site in rows:
                first_seen = job.created_at.strftime("%Y-%m-%d") if job.created_at else ""
                writer.writerow([site.company or site.name, job.title, job.location, first_seen, job.url])
        return len(rows)
    finally:
        db.close()


def main() -> int:
    # DB imports live here so scan_all() can be tested without SQLAlchemy.
    from infrastructure.db.database import DB_PATH, IS_SQLITE, engine
    from infrastructure.db.db_operations import (
        ensure_schema,
        get_sites,
        process_scraped_site,
        record_site_run,
    )
    import seed_comeet_discovery

    started = time.monotonic()
    ensure_schema()
    seed_comeet_discovery.seed()          # adds companies newly listed in SITES; keeps the rest

    sites = get_sites()
    concurrency = int(os.getenv("SCAN_CONCURRENCY", "4"))
    print(f"[scan] {len(sites)} companies, {concurrency} at a time...")
    results = asyncio.run(scan_all(sites, SCRAPERS, concurrency))

    ok = failed = total_jobs = 0
    for site, jobs, error in results:
        label = site.get("company") or site.get("name")
        if jobs is None:
            failed += 1
            print(f"[scan] ✗ {label}: {error}")
            try:
                record_site_run(site["id"], "error", 0, error)
            except Exception as db_error:
                print(f"[scan]   (could not record it: {db_error})")
            continue
        try:
            process_scraped_site(site["id"], jobs, datetime.now(timezone.utc).isoformat())
            ok += 1
            total_jobs += len(jobs)
        except Exception as e:
            failed += 1
            print(f"[scan] ✗ {label}: saving failed: {e}")

    if IS_SQLITE:
        # Fold the WAL file back into jobs.db, so the single file is complete when it's copied.
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        csv_path = os.path.join(os.path.dirname(DB_PATH), "jobs.csv")
        open_jobs = export_open_jobs_csv(csv_path)
        print(f"[scan] {open_jobs} open jobs written to {csv_path}")
    engine.dispose()

    minutes = (time.monotonic() - started) / 60
    print(f"[scan] Done in {minutes:.1f} min: {ok} companies OK, {failed} failed, {total_jobs} jobs scraped.")
    return 0 if ok else 1      # fail the run only when nothing worked (e.g. no network)


if __name__ == "__main__":
    sys.exit(main())
