import os
import sys

os.environ["PUBSUB_EMULATOR_HOST"] = "localhost:8085"
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.append(root_dir)

from infrastructure.quque_system.gcp_pubsub import GCPPubSubClient
from infrastructure.db.db_operations import get_sites, seed_initial_sites

def run_producer():
    seed_initial_sites()
    pubsub = GCPPubSubClient()
    
    topic_name = "links-topic"
    sub_name = "scraper-worker-sub"
    
    pubsub.setup_topic_and_sub(topic_name, sub_name)
    active_links = get_sites()

    if not active_links:
        print("[Producer] No active links found. Exiting.")
        return

    print(f"[Producer] Publishing {len(active_links)} links to topic '{topic_name}'...")
    
    for link in active_links:
        msg_id = pubsub.publish_message(topic_name, link)
        print(f"[Producer] Published message ID: {msg_id}")

if __name__ == "__main__":
    run_producer()