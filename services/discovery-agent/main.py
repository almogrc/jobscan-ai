import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.append(root_dir)

import json
from scraper.scraper_agent import ScraperAgent

from infrastructure.quque_system.pubsub_mock import LocalPubSub
MOCK_DB_URLS = [
    {"name": "Amazon", "url": "https://www.amazon.jobs/content/en/locations/israel/tel-aviv"},
    {"name": "Anthropic", "url": "https://careers.checkpoint.com/index.php?q=&module=cpcareers&a=search&fa%5B%5D=country_ss%3AIsrael&sort="}
]

FIRECRAWL_API_KEY = "fc-a3e7b8277fe64d4790ab67fcbe8cf181"

def main():
    
    links_pubsub = LocalPubSub()
    topic_name = "links"

    for link in MOCK_DB_URLS:
        links_pubsub.publish(topic_name,link)
    print(f"✅ Loaded {len(MOCK_DB_URLS)} tasks into the queue.")

    agent = ScraperAgent(api_key=FIRECRAWL_API_KEY)
    all_new_jobs = []

    while True:
        message=links_pubsub.pull(topic_name)

        if message is None:
            print("📭 Queue is empty. Agent going to sleep.")
            break

        company_name = message["name"]
        url = message["url"]

        try:
            jobs = agent.scan_and_process_jobs(url, company_name)
            all_new_jobs.extend(jobs)

            links_pubsub.acknowledge(topic_name)
            print(f"✅ Acknowledged and cleared {company_name} from queue.")
            
        except Exception as e:
            print(f"❌ Error scanning {company_name}: {e}")
    if all_new_jobs:
        print(f"\n🎉 Boom! Scan completed successfully. Collected a total of {len(all_new_jobs)} jobs:")
        print(json.dumps(all_new_jobs, indent=2, ensure_ascii=False))
    else:
        print("\n⚠️ No jobs found at all. Check the URLs or API limits.")

if __name__ == "__main__":
    main()

