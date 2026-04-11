import json
from scraper.scraper_agent import ScraperAgent

COMPANIES_TO_SCAN = {
    "Amazon": "https://www.amazon.jobs/content/en/locations/israel/tel-aviv",
    "Checkpoint": "https://careers.checkpoint.com/index.php?q=&module=cpcareers&a=search&fa%5B%5D=country_ss%3AIsrael&sort=",
    "Lever-Demo": "https://jobs.lever.co/lever"
}

FIRECRAWL_API_KEY = "fc-a3e7b8277fe64d4790ab67fcbe8cf181"

def main():
    
    agent = ScraperAgent(api_key=FIRECRAWL_API_KEY)
    all_new_jobs = []

    for company_name, url in COMPANIES_TO_SCAN.items():
        try:
            jobs = agent.scan_and_process_jobs(url, company_name)
            all_new_jobs.extend(jobs)
            
        except Exception as e:
            print(f"❌ Error scanning {company_name}: {e}")

if __name__ == "__main__":
    main()

