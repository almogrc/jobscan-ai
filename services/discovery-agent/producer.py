"""
producer.py — Fetches all active sites from the DB and publishes each one
as a JSON message to the 'links-topic' Pub/Sub topic.

Responsibilities (single):
  Read DB -> publish messages. Nothing else.
  The producer does NOT scrape. It does NOT know what a scraper is.
  It is a dumb dispatcher that hands work to workers.

Usage:
    python -m infrastructure.queue_system.producer
"""

import os
import sys

# ---------------------------------------------------------------------------
# Path bootstrap
# Allow running from any working directory by resolving the project root.
# ---------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.append(root_dir)

os.environ.setdefault("PUBSUB_EMULATOR_HOST", "localhost:8085")

from infrastructure.queue_system.gcp_pubsub import GCPPubSubClient   # noqa: E402
from infrastructure.db.db_operations import get_sites, seed_initial_sites  # noqa: E402

TOPIC_NAME = "links-topic"
SUB_NAME   = "scraper-worker-sub"


def run_producer() -> None:
    print("[Producer] Starting...")

    # Seed the DB if it's empty (idempotent — safe to call every time).
    seed_initial_sites()

    pubsub = GCPPubSubClient()

    # setup_topic_and_sub is idempotent: silently ignores AlreadyExists.
    # The producer creates the topic+sub so the worker can start in any order.
    pubsub.setup_topic_and_sub(TOPIC_NAME, SUB_NAME)

    active_sites = get_sites()

    if not active_sites:
        print("[Producer] No active sites found in DB. Nothing to publish. Exiting.")
        return

    print(f"[Producer] Publishing {len(active_sites)} site(s) to '{TOPIC_NAME}'...")

    published = 0
    failed    = 0

    for site in active_sites:
        # Each message is a plain dict: {id, name, url}.
        # The worker is responsible for knowing what to do with each site.
        # We keep the message schema minimal and stable.
        try:
            msg_id = pubsub.publish_message(TOPIC_NAME, site)
            print(f"[Producer]   ✓ Published '{site['name']}' (site_id={site['id']}) → msg_id={msg_id}")
            published += 1
        except Exception as e:
            # One failed publish should not kill the whole run.
            # Log it and continue so other sites still get dispatched.
            print(f"[Producer]   ✗ Failed to publish '{site['name']}': {e}")
            failed += 1

    print(f"[Producer] Done. {published} published, {failed} failed.")


if __name__ == "__main__":
    run_producer()