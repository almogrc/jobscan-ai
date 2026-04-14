import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.append(root_dir)

import json
from scraper.scraper_agent import ScraperAgent
from infrastructure.quque_system.pubsub_mock import LocalPubSub
from infrastructure.db.db_operations import get_sites, process_scraped_site 

FIRECRAWL_API_KEY = "fc-97fea0f266274fa2be9dd96fe2ca5497"

def main():
    links_pubsub = LocalPubSub()
    topic_name = "links"

    db_sites = get_sites()
    
    for site in db_sites:
        links_pubsub.publish(topic_name, site)
    print(f"✅ Loaded {len(db_sites)} active tasks into the queue.")

    agent = ScraperAgent(api_key=FIRECRAWL_API_KEY)
    total_jobs_collected = 0

    while True:
        message = links_pubsub.pull(topic_name)

        if message is None:
            print("📭 Queue is empty. Agent going to sleep.")
            break

        site_id = message["id"]
        company_name = message["name"]
        url = message["url"]

        try:
            jobs, scanned_at = agent.scan_and_process_jobs(url, company_name)
            
            if jobs:
                process_scraped_site(site_id, jobs, scanned_at)
                total_jobs_collected += len(jobs)
            else:
                print(f"⚠️ No jobs found for {company_name}")

            links_pubsub.acknowledge(topic_name)
            print(f"✅ Acknowledged, Saved to DB, and cleared {company_name} from queue.")
            
        except Exception as e:
            print(f"❌ Error scanning/saving {company_name}: {e}")
            links_pubsub.nack(topic_name, message)
            
    if total_jobs_collected > 0:
        print(f"\n🎉 Boom! Scan completed successfully. Collected & Saved {total_jobs_collected} jobs.")
    else:
        print("\n⚠️ No jobs found or saved.")

if __name__ == "__main__":
    main()