from datetime import datetime, timezone

from sqlalchemy import inspect

from .database import Base, SessionLocal, engine
from .model import TargetSite, Job
from .sync_plan import ExistingJob, SyncPlan, plan_sync


class SchemaOutOfDate(RuntimeError):
    pass


def ensure_schema() -> None:
    """
    Create the tables if the DB is empty (a fresh Cloud SQL database included),
    and fail fast with a clear message if jobs.db was created by the old model.
    (The old schema has a UNIQUE url column, which makes inserts fail for
    companies that reuse one careers URL.)
    """
    inspector = inspect(engine)
    if not inspector.has_table("jobs") or not inspector.has_table("target_sites"):
        Base.metadata.create_all(bind=engine)
        return
    columns = {c["name"] for c in inspector.get_columns("jobs")}
    site_columns = {c["name"] for c in inspector.get_columns("target_sites")}
    if "closed_at" not in columns or "company" not in site_columns:
        raise SchemaOutOfDate(
            "jobs.db was created by the old model. Rebuild it once:\n"
            "    python reset_db.py\n"
            "    python seed_comeet_discovery.py\n"
            "then run the producer and the worker again."
        )


def seed_initial_sites():
    db = SessionLocal()
    try:
        if db.query(TargetSite).count() == 0:
            site1 = TargetSite(
                name="Amazon",
                company="Amazon",
                base_url="https://www.amazon.jobs/content/en/locations/israel/tel-aviv"
            )
            site2 = TargetSite(
                name="checkpoint",
                company="Check Point",
                base_url=(
                    "https://careers.checkpoint.com/index.php?q=&module=cpcareers"
                    "&a=search&fa%5B%5D=country_ss%3AIsrael&sort="
                )
            )
            db.add(site1)
            db.add(site2)
            db.commit()
            print("✅ DB: Seeded initial target sites.")
    finally:
        db.close()


def get_sites() -> list[dict]:
    db = SessionLocal()
    try:
        sites = db.query(TargetSite).filter(TargetSite.is_active == True).all()  # noqa: E712
        return [
            {"id": site.id, "name": site.name, "url": site.base_url, "company": site.company or ""}
            for site in sites
        ]
    finally:
        db.close()


def process_scraped_site(site_id: int, scraped_jobs: list[dict], scanned_at_str: str) -> SyncPlan:
    """
    Write one scrape run for one site, in ONE transaction.

    The decisions (insert / update / close / reopen, and the circuit breaker
    for partial scrapes) are made by sync_plan.plan_sync(); this function only
    loads the site's rows and applies the plan.

    Raises on any DB error, after rolling back. The worker nacks the message
    and Pub/Sub redelivers it. (The old version swallowed the error, so the
    worker acked and the run was silently lost.)
    """
    run_ts = datetime.fromisoformat(scanned_at_str)
    db = SessionLocal()
    try:
        rows = db.query(Job).filter(Job.site_id == site_id).all()
        by_id = {row.id: row for row in rows}
        existing = [
            ExistingJob(
                id=row.id,
                job_hash=row.job_hash or "",
                url=row.url or "",
                title=row.title or "",
                location=row.location or "",
                description=row.description or "",
                content_hash=row.content_hash or "",
                last_seen=row.last_seen,
                closed_at=row.closed_at,
            )
            for row in rows
        ]

        plan = plan_sync(existing, scraped_jobs, run_ts)

        for job in plan.inserts:
            db.add(Job(
                site_id=site_id,
                job_hash=job["job_hash"],
                title=job["title"],
                url=job["url"],
                location=job["location"],
                description=job["description"],
                content_hash=job["content_hash"],
                created_at=run_ts,
                updated_at=run_ts,
                last_seen=run_ts,
            ))
        for row_id, changes in plan.updates:
            row = by_id[row_id]
            for key, value in changes.items():
                setattr(row, key, value)
            if "content_hash" in changes:
                row.updated_at = run_ts
        for row_id in plan.seen_ids:
            by_id[row_id].last_seen = run_ts
        for row_id in plan.reopen_ids:
            by_id[row_id].closed_at = None
        for row_id in plan.close_ids:
            by_id[row_id].closed_at = run_ts

        site = db.get(TargetSite, site_id)
        if site is not None:
            site.last_run_at = run_ts
            site.last_status = "ok" if plan.scraped_count else "empty"
            site.last_count  = plan.scraped_count
            site.last_error  = plan.note

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(
        f"✅ DB: site_id={site_id} — {len(plan.inserts)} new, {len(plan.updates)} changed, "
        f"{len(plan.seen_ids)} seen, {len(plan.reopen_ids)} reopened, "
        f"{len(plan.close_ids)} closed, {plan.skipped} skipped."
    )
    if plan.note:
        print(f"⚠️ DB: site_id={site_id} — {plan.note}")
    return plan


def record_site_run(site_id: int, status: str, count: int = 0, error: str = "") -> None:
    """Remember how the last run of a site went (used when the scraper itself failed)."""
    db = SessionLocal()
    try:
        site = db.get(TargetSite, site_id)
        if site is None:
            return
        site.last_run_at = datetime.now(timezone.utc)
        site.last_status = status
        site.last_count  = count
        site.last_error  = (error or "")[:2000]
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
