from datetime import datetime, timezone
from .database import SessionLocal
from .model import TargetSite, Job

def seed_initial_sites():
    db = SessionLocal()
    try:
        if db.query(TargetSite).count() == 0:
            site1 = TargetSite(name="Amazon", base_url="https://www.amazon.jobs/content/en/locations/israel/tel-aviv")
            site2 = TargetSite(name="checkpoint", base_url="https://careers.checkpoint.com/index.php?q=&module=cpcareers&a=search&fa%5B%5D=country_ss%3AIsrael&sort=")
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
    db = SessionLocal()
    try:
        run_timestamp = datetime.fromisoformat(scanned_at_str)
        
        for job_data in scraped_jobs:
            existing_job = db.query(Job).filter(Job.url == job_data["url"]).first()
            if existing_job:
                existing_job.last_seen = run_timestamp 
            else:
                new_job = Job(
                    site_id=site_id,
                    title=job_data["title"],
                    url=job_data["url"],
                    job_hash=job_data.get("job_hash", ""),
                    last_seen=run_timestamp
                )
                db.add(new_job)
                
        db.commit()

        expired_jobs = db.query(Job).filter(
            Job.site_id == site_id,
            Job.last_seen < run_timestamp.date()
        ).all()

        if expired_jobs:
            print(f"🧹 Found {len(expired_jobs)} expired jobs for site {site_id}:")
            for job in expired_jobs:
                print(f"   [-] Removingּ: {job.title}")

        deleted_count = db.query(Job).filter(
            Job.site_id == site_id,
            Job.last_seen < run_timestamp.date()
        ).delete(synchronize_session=False)
        
        db.commit()
        print(f"✅ DB: Cleaned up {deleted_count} old jobs for site_id {site_id}")
        
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()