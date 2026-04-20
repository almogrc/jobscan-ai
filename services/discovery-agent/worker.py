import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()
os.environ["PUBSUB_EMULATOR_HOST"] = os.getenv("PUBSUB_EMULATOR_HOST", "localhost:8085")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.append(root_dir)

from scraper.scraper_agent import ScraperAgent
from infrastructure.quque_system.gcp_pubsub import GCPPubSubClient
from infrastructure.db.db_operations import process_scraped_site

def process_message(message):
    try:
        site_data = json.loads(message.data.decode("utf-8"))
        print(f"[Worker] Processing site: {site_data.get('name', 'Unknown')}")
        
        agent = ScraperAgent(api_key=FIRECRAWL_API_KEY)
        
        jobs, scanned_at = agent.scan_and_process_jobs(
            target_url=site_data["url"],
            company_name=site_data["name"]
        )

        process_scraped_site(
            site_id=site_data["id"], 
            scraped_jobs=jobs, 
            scanned_at_str=scanned_at
        )
        
        message.ack()
        print(f"[Worker] Successfully processed and ACKed site: {site_data['name']}")
        
    except Exception as e:
        print(f"[Worker] Error processing message: {e}")
        message.nack() # דוחה את ההודעה מיידית כדי שתחזור לתור ולא תיתקע באוויר

def run_worker():
    print("[Worker] Starting up and connecting to emulator...")
    pubsub = GCPPubSubClient()
    
    # מוודאים תשתית (למקרה שהפועל קם לפני הפרודוסר)
    pubsub.setup_topic_and_sub("links-topic", "scraper-worker-sub")
    
    print("[Worker] Listening for messages...")
    future = pubsub.listen("scraper-worker-sub", process_message)
    
    try:
        future.result() # כאן הוא ננעל ומחכה להודעות
    except KeyboardInterrupt:
        future.cancel()
        print("\n[Worker] Shutting down cleanly.")

if __name__ == "__main__":
    run_worker()