"""
worker.py — Pub/Sub listener and scraper factory.

Responsibilities (and ONLY these):
  1. Decode incoming Pub/Sub messages
  2. Route to the correct scraper via scraper_factory()
  3. Persist results via process_scraped_site()
  4. Ack or nack the message with strict correctness

This file contains ZERO scraping logic. Every scraper lives in its own
module under scrapers/. To add a new site, add one import and one `if`
branch in scraper_factory() — nothing else changes.

Architecture:
  process_message()        ← Pub/Sub callback (sync, runs in thread pool)
    └─ scraper_factory()   ← async router
         ├─ scrape_checkpoint()   from scrapers.checkpoint
         └─ scrape_amazon()       from scrapers.amazon

ACK CONTRACT:
  message.ack()  → ONLY after process_scraped_site() commits successfully
  message.nack() → on ANY exception; Pub/Sub will redeliver the message

Usage:
    python -m infrastructure.queue_system.worker
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir    = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.insert(0, root_dir)

os.environ.setdefault("PUBSUB_EMULATOR_HOST", "localhost:8085")

# ---------------------------------------------------------------------------
# Internal imports  (after path bootstrap)
# ---------------------------------------------------------------------------
from scrapers.checkpoint import scrape_checkpoint                    # noqa: E402
from scrapers.amazon import scrape_amazon                            # noqa: E402
from scrapers.comeet import scrape_comeet                            # noqa: E402
from scrapers.lever import scrape_lever                              # noqa: E402
from scrapers.greenhouse import scrape_greenhouse                    # noqa: E402
from infrastructure.queue_system.gcp_pubsub import GCPPubSubClient  # noqa: E402
from infrastructure.db.db_operations import process_scraped_site    # noqa: E402

TOPIC_NAME = "links-topic"
SUB_NAME   = "scraper-worker-sub"


# ===========================================================================
# Factory
# ===========================================================================

async def scraper_factory(site_name: str, target_url: str) -> list[dict] | None:
    """
    Map site_name -> the correct scraper coroutine and return its results.

    Return values:
      list[dict]  — scraped jobs (may be empty for placeholder sites)
      None        — site_name is unknown; caller must nack (not redeliver loop)

    WHY RETURN None FOR UNKNOWN SITES (not raise)?
    Raising triggers a nack and Pub/Sub redelivery — correct for transient
    failures like network errors. But an unknown site_name is a configuration
    bug; redelivery won't fix it and will hammer the queue. Returning None
    signals "nack this once and log a warning" without an infinite loop.

    HOW TO ADD A NEW SITE:
      1. Create scrapers/newsite.py  with  async def scrape_newsite(url) -> list[dict]
      2. Add one import at the top of this file
      3. Add one `if name == "newsite":` branch below
      That's it. process_message() does not change.
    """
    name = site_name.lower().strip()

    if name == "checkpoint":
        return await scrape_checkpoint(target_url)

    if name == "amazon":
        return await scrape_amazon(target_url)

    if name == "comeet":
        return await scrape_comeet(target_url)

    if name == "lever":
        return await scrape_lever(target_url)

    if name == "greenhouse":
        return await scrape_greenhouse(target_url)

    print(f"[Worker] WARNING: No scraper registered for site '{site_name}'.")
    return None


# ===========================================================================
# Pub/Sub callback
# ===========================================================================

def process_message(message) -> None:
    """
    Pub/Sub push callback. Called from the subscriber's background thread.

    WHY asyncio.run() HERE?
    The synchronous Pub/Sub client invokes this function from a thread pool.
    Our scrapers are async (Playwright). asyncio.run() creates a fresh event
    loop per message — safe because messages are processed sequentially.
    If we later move to concurrent processing, we'd share a single event loop
    instead, but sequential is correct and simple for now.
    """

    # --- 1. Decode payload ---
    try:
        site_data = json.loads(message.data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # A message we can never decode is not worth redelivering.
        # Nack once and move on — it will go to the dead-letter topic if configured.
        print(f"[Worker] ERROR: Cannot decode message payload: {e}")
        message.nack()
        return

    site_id   = site_data.get("id")
    site_name = site_data.get("name", "")
    site_url  = site_data.get("url", "")

    print(f"[Worker] ← Received: '{site_name}' (site_id={site_id})")

    # --- 2. Route to scraper ---
    try:
        jobs = asyncio.run(scraper_factory(site_name, site_url))
    except Exception as e:
        print(f"[Worker] ERROR: Scraper raised an exception for '{site_name}': {e}")
        message.nack()
        return

    # --- 3. Handle factory return value ---
    if jobs is None:
        # Unknown site — nack without logging an exception (already warned above)
        message.nack()
        return

    if not jobs:
        # Placeholder (Amazon) or genuinely zero results — ack cleanly
        print(f"[Worker] No jobs to save for '{site_name}'. Acking.")
        message.ack()
        return

    # --- 4. Persist to DB ---
    #
    # All jobs in a single run share ONE scanned_at timestamp. This matters
    # because process_scraped_site() deletes jobs where last_seen < this
    # timestamp. If we stamped each job individually, the first job written
    # would have an earlier last_seen than the last, and the cleanup query
    # could incorrectly prune jobs from the same run.
    scanned_at = datetime.now(timezone.utc).isoformat()

    try:
        process_scraped_site(
            site_id=site_id,
            scraped_jobs=jobs,
            scanned_at_str=scanned_at,
        )
        message.ack()   # ← THE ONLY ack() CALL IN THIS FUNCTION
        print(f"[Worker] ✓ '{site_name}': {len(jobs)} jobs committed. Message acked.")

    except Exception as e:
        print(f"[Worker] ERROR: DB commit failed for '{site_name}': {e}")
        message.nack()  # Pub/Sub redelivers; the scrape work is not lost


# ===========================================================================
# Entry point
# ===========================================================================

def run_worker() -> None:
    print("[Worker] Starting up...")
    pubsub = GCPPubSubClient()

    # Ensure topic + subscription exist even if producer hasn't run yet.
    # setup_topic_and_sub() is idempotent — safe to call on every startup.
    pubsub.setup_topic_and_sub(TOPIC_NAME, SUB_NAME)

    print(f"[Worker] Listening on '{SUB_NAME}'. Press Ctrl+C to stop.")
    future = pubsub.listen(SUB_NAME, process_message)

    try:
        future.result()          # blocks until keyboard interrupt or fatal error
    except KeyboardInterrupt:
        future.cancel()
        print("\n[Worker] Shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    run_worker()