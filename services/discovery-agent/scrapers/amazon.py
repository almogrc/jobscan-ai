"""
scrapers/amazon.py — Async API scraper for Amazon Jobs (Israel / Tel Aviv).

Public API (the only symbol worker.py needs):
    await scrape_amazon(target_url: str) -> list[dict]

Each dict has exactly these keys (matching the Job model schema):
    title     : str   — fields.title[0]
    url       : str   — fields.urlNextStep[0]
    location  : str   — fields.normalizedLocation[0]
    job_hash  : str   — fields.icimsJobId[0]   (string, e.g. "2982451")

Strategy: HTTP POST to Amazon's internal jobs search API using aiohttp.
No browser / Playwright needed — this is a clean JSON API.

⚠️  IMPORTANT — CREDENTIALS WILL EXPIRE, AND THEY ARE NOT IN THE CODE:
    The cookies and API key are read from two environment variables:
        AMAZON_JOBS_COOKIES   — the full `Cookie:` header value
        AMAZON_JOBS_API_KEY   — the `x-api-key:` header value
    (They used to be pasted into this file, which is in a public repo.)
    If either is missing the scraper logs it and returns [].
    They come from a live browser session.
    Session cookies typically expire within hours to days.
    API_KEY may be rotated by Amazon periodically.
    When requests start returning 401/403 or empty results:
      1. Open https://www.amazon.jobs/content/en/locations/israel/tel-aviv
         in your browser with DevTools → Network tab open.
      2. Trigger any search/filter action.
      3. Find the POST to /api/jobs/search, copy the Cookie header and
         x-api-key header, and put them in your .env / Secret Manager.
"""

import asyncio
import os
import random
from copy import deepcopy

import aiohttp

# ===========================================================================
# Credentials  ← set AMAZON_JOBS_COOKIES / AMAZON_JOBS_API_KEY when sessions expire
# ===========================================================================

SESSION_COOKIES = os.getenv("AMAZON_JOBS_COOKIES", "")
API_KEY         = os.getenv("AMAZON_JOBS_API_KEY", "")

# ===========================================================================
# API constants
# ===========================================================================

API_ENDPOINT = "https://www.amazon.jobs/api/jobs/search?is_als=true"
REFERER      = "https://www.amazon.jobs/content/en/locations/israel/tel-aviv"
BASE_JOB_URL = "https://www.amazon.jobs"

# Number of jobs to request per page.
# Must match the `size` field in the request body.
PAGE_SIZE = 10

# ===========================================================================
# HTTP headers
# Replicated exactly from the captured cURL, minus cookies (sent separately).
# ===========================================================================

_HEADERS = {
    "Accept":                   "application/json",
    "Accept-Language":          "en-US,en;q=0.9",
    "Connection":               "keep-alive",
    "Content-Type":             "text/plain;charset=UTF-8",
    "Origin":                   "https://www.amazon.jobs",
    "Referer":                  REFERER,
    "Sec-Fetch-Dest":           "empty",
    "Sec-Fetch-Mode":           "cors",
    "Sec-Fetch-Site":           "same-origin",
    "User-Agent":               (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua":                '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile":         "?0",
    "sec-ch-ua-platform":       '"Windows"',
    "x-api-key":                API_KEY,
    "Cookie":                   SESSION_COOKIES,
}

# ===========================================================================
# Request body template
#
# WHY A TEMPLATE (not rebuilt per request)?
# The body is large and 99% identical between pages. We deepcopy it each
# iteration and only mutate `start` — avoids repetition and makes it easy
# to compare against the original cURL if something breaks.
#
# Fields explained:
#   start            — result offset (0, 10, 20 …)  ← only field that changes
#   size             — results per page (must stay in sync with PAGE_SIZE)
#   accessLevel      — "EXTERNAL" = public jobs only
#   locationFacets   — country=IL + city=Tel Aviv-Yafo
#   excludeFacets    — strip confidential / internal jobs
#   sort             — SCORE DESCENDING (default ranking)
#   cookieInfo       — Amazon's API mirrors the Cookie header inside the body
#                      (dual-channel auth). Keep in sync with SESSION_COOKIES.
# ===========================================================================

_BODY_TEMPLATE: dict = {
    "accessLevel": "EXTERNAL",
    "contentFilterFacets": [
        {"name": "primarySearchLabel", "requestedFacetCount": 9999}
    ],
    "excludeFacets": [
        {"name": "isConfidential",   "values": [{"name": "1"}]},
        {"name": "businessCategory", "values": [{"name": "a-confidential-job"}]},
    ],
    "filterFacets":   [],
    "includeFacets":  [],
    "jobTypeFacets":  [],
    "locationFacets": [
        [
            {"name": "country",            "requestedFacetCount": 9999, "values": [{"name": "IL"}]},
            {"name": "normalizedStateName","requestedFacetCount": 9999},
            {"name": "normalizedCityName", "requestedFacetCount": 9999, "values": [{"name": "Tel Aviv-Yafo"}]},
        ]
    ],
    "query":     "",
    "size":      PAGE_SIZE,
    "start":     0,           # ← mutated per page
    "treatment": "OM",
    "cookieInfo": SESSION_COOKIES,
    "sort": {
        "sortOrder": "DESCENDING",
        "sortType":  "SCORE",
    },
}


# ===========================================================================
# Field extraction helpers
# ===========================================================================

def _safe_first(fields: dict, key: str) -> str:
    """
    Safely extract the first element of a list field from the API response.

    WHY [0] WITH A FALLBACK?
    Amazon's API returns all string fields as single-element lists
    (e.g. `"title": ["Software Engineer"]`). This is their schema convention.
    We want the raw string, not the list. Using index [0] directly would
    raise IndexError on any missing/empty field, which would kill the whole
    scrape. A defensive helper means one bad job card doesn't lose the rest.
    """
    value = fields.get(key, [])
    if isinstance(value, list) and value:
        return str(value[0]).strip()
    return ""


def _map_hit(hit: dict) -> dict | None:
    """
    Convert one searchHits item into our internal job schema dict.

    Returns None if the hit is missing the minimum required fields
    (title + job_id), so the caller can skip it cleanly.

    URL STRATEGY:
    The API returns two URL fields:
      urlNextStep  → "https://account.amazon.com/jobs/3199549/apply"
                     This is the APPLY redirect, not the job listing page.
                     It's broken as a "view this job" link.
      (no direct listing URL field in the API response)

    The correct job detail page URL follows a fixed pattern:
      https://www.amazon.jobs/en/jobs/{icimsJobId}
      e.g. https://www.amazon.jobs/en/jobs/3199549

    We construct it from icimsJobId, which is always present when the
    job is a real listing. This is stable and human-readable.
    """
    fields = hit.get("fields", {})

    title    = _safe_first(fields, "title")
    job_hash = _safe_first(fields, "icimsJobId")
    location = _safe_first(fields, "normalizedLocation")

    if not title or not job_hash:
        return None   # skip malformed hits

    # Construct the canonical job detail page URL from the job ID.
    url = f"{BASE_JOB_URL}/en/jobs/{job_hash}"

    return {
        "title":    title,
        "url":      url,
        "location": location,
        "job_hash": job_hash,
    }


# ===========================================================================
# Core pagination loop
# ===========================================================================

async def _fetch_page(session: aiohttp.ClientSession, start: int) -> dict:
    """
    POST one page request and return the parsed JSON response.

    WHY `text/plain;charset=UTF-8` as Content-Type?
    Amazon's API declares this content type (unusual for JSON). aiohttp's
    `json=` parameter would send `application/json`, which the server may
    reject. We serialise to a string manually and send it as `data=` so
    the Content-Type header is respected exactly as captured.

    Raises:
        aiohttp.ClientResponseError  — non-2xx HTTP status
        aiohttp.ContentTypeError     — response is not valid JSON
        asyncio.TimeoutError         — request exceeded timeout
    """
    import json as _json

    body = deepcopy(_BODY_TEMPLATE)
    body["start"] = start

    # Serialise to string — Content-Type is text/plain, not application/json
    payload = _json.dumps(body, separators=(",", ":"))

    async with session.post(
        API_ENDPOINT,
        data=payload,                    # raw string body
        headers=_HEADERS,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as response:
        response.raise_for_status()      # raise on 4xx/5xx
        return await response.json(content_type=None)
        # content_type=None: aiohttp validates Content-Type by default.
        # Amazon may return "text/plain" on the response too, which would
        # raise ContentTypeError even though the body is valid JSON.
        # Passing None disables that check safely.


async def scrape_amazon(target_url: str) -> list[dict]:
    """
    Fetch ALL Amazon job postings in Israel (Tel Aviv) via the internal API.

    Args:
        target_url: Passed in by the worker from the DB record. Not used
                    directly (the endpoint is fixed), but kept for interface
                    consistency with other scrapers in the factory.

    Returns:
        Flat list of job dicts: [{title, url, location, job_hash}, ...]

    PAGINATION STRATEGY:
        start = 0, 10, 20 …  (incremented by PAGE_SIZE each iteration)

    STOP CONDITIONS:
        1. searchHits is empty            → walked off the end of results
        2. len(searchHits) < PAGE_SIZE    → this is the last (partial) page
        3. HTTP error / timeout           → log + break, return what we have

    WHY STOP ON PARTIAL PAGE (condition 2)?
    If the API returns fewer results than requested, there are no more pages.
    Without this check we'd make one extra round-trip, get 0 results, and
    stop — which works but wastes a request. Early exit is cleaner.
    """
    if not SESSION_COOKIES or not API_KEY:
        print("[Amazon] Skipped: set AMAZON_JOBS_COOKIES and AMAZON_JOBS_API_KEY "
              "(see the note at the top of scrapers/amazon.py).")
        return []

    all_jobs:  list[dict] = []
    seen_urls: set[str]   = set()

    # aiohttp's ClientSession is an async context manager.
    # We create ONE session for the full scrape (reuses the TCP connection),
    # rather than one session per page (which would reconnect every time).
    async with aiohttp.ClientSession() as session:
        start = 0
        page_num = 0

        while True:
            page_num += 1
            print(f"[Amazon] Fetching offset={start} (page {page_num})...")

            try:
                data = await _fetch_page(session, start)
            except aiohttp.ClientResponseError as e:
                print(
                    f"[Amazon] HTTP error at offset={start}: "
                    f"{e.status} {e.message}. "
                    f"{'Session cookies may have expired.' if e.status in (401, 403) else ''}"
                )
                break   # return whatever we collected so far
            except Exception as e:
                print(f"[Amazon] Request failed at offset={start}: {e}")
                break

            hits = data.get("searchHits", [])

            if not hits:
                print(f"[Amazon] No hits at offset={start}. Pagination complete.")
                break

            new_this_page = 0
            for hit in hits:
                job = _map_hit(hit)
                if job is None:
                    continue
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    all_jobs.append(job)
                    new_this_page += 1

            print(
                f"[Amazon]   {len(hits)} hits received, "
                f"{new_this_page} new unique jobs "
                f"(running total: {len(all_jobs)})"
            )

            # Partial page → this was the last page
            if len(hits) < PAGE_SIZE:
                print(f"[Amazon] Partial page ({len(hits)} < {PAGE_SIZE}). End of results.")
                break

            start += PAGE_SIZE

            # Polite delay between requests.
            # This is an API (not a browser), so shorter delays are fine,
            # but we still randomise to avoid a perfectly metronomic pattern.
            delay = random.uniform(0.5, 1.5)
            print(f"[Amazon] Waiting {delay:.1f}s before next page...")
            await asyncio.sleep(delay)

    print(f"[Amazon] Scrape complete. {len(all_jobs)} unique jobs found.")
    return all_jobs