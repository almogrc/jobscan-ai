import hashlib
from datetime import datetime, timezone
from firecrawl import Firecrawl
from schemas import JobBoard

class ScraperAgent:
    def __init__(self, api_key: str):
        self.app = Firecrawl(api_key=api_key)

    def scan_and_process_jobs(self, target_url: str, company_name: str) -> tuple[list[dict], str]:
        print(f"[*] Agent starting scan for {company_name} at {target_url}...")
        
        scan_time = datetime.now(timezone.utc).isoformat()
        
        result = self.app.scrape(
            target_url,
            formats=[{
                "type": "json",
                "schema": JobBoard.model_json_schema()
            }]
        )
        
        if hasattr(result, 'json'):
            extracted_data = result.json
        elif isinstance(result, dict):
            extracted_data = result.get('json', {})
        else:
            extracted_data = result
            
        extracted_jobs = extracted_data.get('jobs', [])
        processed_jobs = []

        for job in extracted_jobs:
            raw_string = f"{company_name}_{job.get('title')}_{job.get('url')}"
            job_hash = hashlib.md5(raw_string.encode('utf-8')).hexdigest()
            
            final_job = {
                "id": job.get("id"),
                "title": job.get("title"),
                "url": job.get("url"),
                "location": job.get("location"),
                "created_at": job.get("created_at"),
                "job_hash": job_hash
            }
            processed_jobs.append(final_job)
            
        return processed_jobs, scan_time