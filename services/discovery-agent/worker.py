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
  process_message(message)       ← Pub/Sub callback (runs in the client's thread pool)
    └─ handle_site_message(data)  ← transport-free: returns ACK or NACK
         ├─ scraper_factory()     ← async router
         └─ process_scraped_site()

handle_site_message() doesn't know about Pub/Sub objects, so the same code
can later sit behind a Cloud Run push endpoint (2xx = ack, 5xx = nack).

ACK CONTRACT:
  ACK   → results committed to the DB (including an empty run)
  ACK   → the message can never succeed: bad JSON, unknown site.
          Redelivering it only loops forever (there is no dead-letter
          topic locally), so we log it loudly and drop it.
  NACK  → the scraper raised, or the DB write failed. Pub/Sub redelivers.

Usage (from services/discovery-agent):
    python worker.py
Env:
    WORKER_CONCURRENCY   messages processed at the same time (default 4)
"""

import asyncio
import enum
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

# ---------------------------------------------------------------------------
# Internal imports  (after path bootstrap)
# ---------------------------------------------------------------------------
from scrapers.checkpoint import scrape_checkpoint                    # noqa: E402
from scrapers.amazon import scrape_amazon                            # noqa: E402
from scrapers.comeet import scrape_comeet                            # noqa: E402
from scrapers.lever import scrape_lever                              # noqa: E402
from scrapers.greenhouse import scrape_greenhouse                    # noqa: E402
from infrastructure.queue_system.gcp_pubsub import GCPPubSubClient  # noqa: E402
from infrastructure.db.db_operations import (                        # noqa: E402
    ensure_schema,
    process_scraped_site,
    record_site_run,
)

TOPIC_NAME = "links-topic"
SUB_NAME   = "scraper-worker-sub"


class Outcome(enum.Enum):
    ACK  = "ack"
    NACK = "nack"


# ===========================================================================
# Factory
# ===========================================================================

async def scraper_factory(site_name: str, target_url: str) -> list[dict] | None:
    """
    Map site_name -> the correct scraper coroutine and return its results.

    Return values:
      list[dict]  — scraped jobs (may be empty)
      None        — site_name is unknown (a configuration bug, not a transient error)

    HOW TO ADD A NEW SITE:
      1. Create scrapers/newsite.py  with  async def scrape_newsite(url) -> list[dict]
      2. Add one import at the top of this file
      3. Add one `if name == "newsite":` branch below
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
# Message handling (no Pub/Sub objects in here)
# ===========================================================================

def handle_site_message(data: bytes) -> Outcome:
    # --- 1. Decode payload ---
    try:
        site_data = json.loads(data.decode("utf-8"))
        site_id   = int(site_data["id"])
        site_name = str(site_data.get("name", ""))
        site_url  = str(site_data.get("url", ""))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
        print(f"[Worker] ERROR: Dropping a message that can't be decoded: {e}")
        return Outcome.ACK

    label = site_data.get("company") or site_name
    print(f"[Worker] ← Received: '{label}' (site_id={site_id}, scraper={site_name})")

    # --- 2. Scrape ---
    try:
        jobs = asyncio.run(scraper_factory(site_name, site_url))
    except Exception as e:
        print(f"[Worker] ERROR: Scraper raised for '{label}': {e}")
        try:
            record_site_run(site_id, "error", 0, f"{type(e).__name__}: {e}")
        except Exception as db_error:
            print(f"[Worker] (could not record the error: {db_error})")
        return Outcome.NACK

    if jobs is None:
        print(f"[Worker] ERROR: Dropping '{label}': unknown scraper '{site_name}'. Fix target_sites.name.")
        return Outcome.ACK

    # --- 3. Persist (also for an empty run: it records the run and lets
    #        sync_plan close jobs that haven't been seen for a week) ---
    #
    # All jobs in a single run share ONE scanned_at timestamp.
    scanned_at = datetime.now(timezone.utc).isoformat()
    try:
        process_scraped_site(site_id=site_id, scraped_jobs=jobs, scanned_at_str=scanned_at)
    except Exception as e:
        print(f"[Worker] ERROR: DB commit failed for '{label}': {e}")
        return Outcome.NACK

    print(f"[Worker] ✓ '{label}': {len(jobs)} job(s) processed.")
    return Outcome.ACK


def process_message(message) -> None:
    """
    Pub/Sub callback. The client calls it from a thread pool, so several
    messages run at the same time (capped by WORKER_CONCURRENCY).
    asyncio.run() gives each call its own event loop in its own thread.
    """
    outcome = handle_site_message(message.data)
    if outcome is Outcome.ACK:
        message.ack()
    else:
        message.nack()


# ===========================================================================
# Entry point
# ===========================================================================

def run_worker() -> None:
    print("[Worker] Starting up...")
    ensure_schema()
    pubsub = GCPPubSubClient()

    # Ensure topic + subscription exist even if producer hasn't run yet.
    # setup_topic_and_sub() is idempotent — safe to call on every startup.
    pubsub.setup_topic_and_sub(TOPIC_NAME, SUB_NAME)

    concurrency = int(os.getenv("WORKER_CONCURRENCY", "4"))
    print(f"[Worker] Listening on '{SUB_NAME}' (up to {concurrency} at a time). Press Ctrl+C to stop.")
    future = pubsub.listen(SUB_NAME, process_message, max_messages=concurrency)

    try:
        future.result()          # blocks until keyboard interrupt or fatal error
    except KeyboardInterrupt:
        future.cancel()
        print("\n[Worker] Shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    run_worker()
