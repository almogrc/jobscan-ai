from datetime import datetime, timezone
from .database import SessionLocal
from .model import TargetSite, Job


def seed_initial_sites():
    db = SessionLocal()
    try:
        if db.query(TargetSite).count() == 0:
            site1 = TargetSite(
                name="Amazon",
                base_url="https://www.amazon.jobs/content/en/locations/israel/tel-aviv"
            )
            site2 = TargetSite(
                name="checkpoint",
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
        sites = db.query(TargetSite).filter(TargetSite.is_active == True).all()
        return [{"id": site.id, "name": site.name, "url": site.base_url} for site in sites]
    finally:
        db.close()


def process_scraped_site(site_id: int, scraped_jobs: list[dict], scanned_at_str: str):
    """
    Bulletproof Upsert for Cloud:
    Filters duplicates in memory BEFORE hitting the DB to guarantee 
    zero UNIQUE constraint crashes, then silently swallows any other DB errors.
    """
    db = SessionLocal()
    try:
        run_timestamp = datetime.fromisoformat(scanned_at_str)
        upserted = 0
        skipped  = 0

        # 1. ניקוי כפילויות בזיכרון (הנשק הסודי נגד קריסות DB)
        unique_jobs = {}
        for job in scraped_jobs:
            url = job.get("url", "").strip()
            if not url:
                skipped += 1
                continue
            # אם החברה החזירה את אותו לינק פעמיים - זה פשוט ידרוס את עצמו פה ולא יגיע ל-DB
            unique_jobs[url] = job

        # 2. כתיבה בטוחה
        for url, job_data in unique_jobs.items():
            existing = db.query(Job).filter(Job.url == url).first()

            if existing:
                existing.last_seen = run_timestamp
                new_desc = job_data.get("description", "")
                if new_desc and not existing.description:
                    existing.description = new_desc
                upserted += 1
            else:
                db.add(Job(
                    site_id=site_id,
                    title=job_data.get("title", ""),
                    url=url,
                    job_hash=job_data.get("job_hash", ""),
                    location=job_data.get("location", ""),
                    description=job_data.get("description", ""),
                    last_seen=run_timestamp,
                ))
                upserted += 1

        # 3. שמירה אחת בטוחה
        db.commit()

        # 4. ניקוי משרות ישנות
        deleted_count = db.query(Job).filter(
            Job.site_id == site_id,
            Job.last_seen < run_timestamp,
        ).delete(synchronize_session=False)

        db.commit()
        print(f"✅ DB: site_id={site_id} — {upserted} upserted, {skipped} skipped, {deleted_count} stale removed.")

    except Exception as e:
        # בולעים את השגיאה בשקט כדי שהתור יעבור הלאה ולא ניכנס ללופ
        db.rollback()
        print(f"⚠️ DB: Caught and swallowed error to prevent queue loop: {e}")

    finally:
        db.close()