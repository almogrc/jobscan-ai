"""
scrapers/greenhouse.py — Greenhouse ATS scraper with double-fetch description enrichment.

Strategy (two-phase):
  Phase 1 — List fetch:
    GET boards-api.greenhouse.io/v1/boards/{slug}/jobs
    Returns all jobs with title, url, location, id.
    Filter to Israel-only jobs.

  Phase 2 — Description fetch (concurrent):
    For each Israel job, GET boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}
    Returns the full job object including `content` (HTML job description).
    Strip HTML with BeautifulSoup → plain text → inject as `description`.

    All Phase 2 requests run concurrently via asyncio.gather(), bounded by a
    semaphore so we never fire more than DESC_CONCURRENCY requests at once.

Public API:
    await scrape_greenhouse(target_url: str) -> list[dict]

Return schema (one dict per job):
    title       : str  — job.title
    url         : str  — job.absolute_url
    location    : str  — job.location.name
    job_hash    : str  — str(job.id)
    description : str  — plain text stripped from job.content HTML

Dependencies:
    pip install aiohttp beautifulsoup4 lxml
"""

import asyncio

import aiohttp
from bs4 import BeautifulSoup

# ===========================================================================
# API endpoints
# ===========================================================================

# Phase 1 — job list  (no ?content=true — that field is always empty on list)
GH_LIST_API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

# Phase 2 — individual job detail (contains full `content` HTML)
GH_JOB_API  = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

_HEADERS = {
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Maximum concurrent description-fetch requests.
# Greenhouse's public API is rate-limited. 10 concurrent is fast (a board
# with 80 IL jobs finishes in ~3 round-trips) while staying well under limits.
DESC_CONCURRENCY = 10

# ===========================================================================
# Israel location keywords
# ===========================================================================

_IL_KEYWORDS = (
    "israel",
    "tel aviv",
    "tel-aviv",
    "tlv",
    "herzliya",
    "herzelia",
    "haifa",
    "petah tikva",
    "petach tikva",
    "ra'anana",
    "raanana",
    "netanya",
    "jerusalem",
    "ramat gan",
    "kfar saba",
    "rishon",
    "rehovot",
    "beer sheva",
    "be'er sheva",
    "hod hasharon",
    "givatayim",
    "holon",
    "bnei brak",
)


def _is_israel(location_name: str) -> bool:
    loc = location_name.lower()
    return any(kw in loc for kw in _IL_KEYWORDS)


# ===========================================================================
# HTML → plain text
# ===========================================================================

def _strip_html(html: str) -> str:
    """
    Convert an HTML job description to clean plain text.

    WHY lxml PARSER?
    Greenhouse `content` fields are well-formed HTML (they come from a WYSIWYG
    editor). lxml parses them correctly and is significantly faster than
    html.parser for repeated calls inside a concurrent gather().

    WHY get_text(separator=" ", strip=True)?
    `separator=" "` puts a space between block-level elements so words from
    adjacent <p> or <li> tags don't run together.
    `strip=True` removes leading/trailing whitespace from each text node.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator=" ", strip=True)


# ===========================================================================
# Phase 1 — list mapping
# ===========================================================================

def _map_job_from_list(job: dict) -> dict | None:
    """
    Build a partial job dict from the Phase 1 list response.
    `description` is intentionally absent here — Phase 2 injects it.
    Returns None if the minimum required fields are missing.
    """
    title = (job.get("title") or "").strip()
    url   = (job.get("absolute_url") or "").strip()

    if not title or not url:
        return None

    return {
        "title":       title,
        "url":         url,
        "location":    (job.get("location", {}).get("name") or "").strip(),
        "job_hash":    str(job.get("id") or "").strip(),
        "description": "",          # placeholder — filled by Phase 2
        "_gh_id":      job.get("id"),   # internal use only, stripped before return
    }


# ===========================================================================
# Phase 2 — individual description fetch
# ===========================================================================

async def _fetch_description(
    session:     aiohttp.ClientSession,
    semaphore:   asyncio.Semaphore,
    board_token: str,
    job:         dict,
) -> dict:
    """
    Fetch the full job detail and inject a plain-text description into `job`.

    Always returns the job dict — on any error, description stays "".
    This means a failed description fetch degrades gracefully (job still
    saved, just without description) rather than failing the whole scrape.

    SEMAPHORE PATTERN:
    `async with semaphore:` acquires one slot from the pool before making
    the HTTP request, and releases it when the request completes. Combined
    with asyncio.gather(), this means at most DESC_CONCURRENCY requests
    are in-flight simultaneously — the rest wait in the event loop queue.
    """
    gh_id = job.get("_gh_id")
    if not gh_id:
        return job

    url = GH_JOB_API.format(board_token=board_token, job_id=gh_id)

    async with semaphore:
        try:
            async with session.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
                html_content = data.get("content") or ""
                job["description"] = _strip_html(html_content)

        except aiohttp.ClientResponseError as e:
            print(f"[Greenhouse] Description fetch HTTP {e.status} for job_id={gh_id}. "
                  f"Continuing without description.")
        except asyncio.TimeoutError:
            print(f"[Greenhouse] Description fetch timeout for job_id={gh_id}. "
                  f"Continuing without description.")
        except Exception as e:
            print(f"[Greenhouse] Description fetch error for job_id={gh_id}: {e}")

    return job


# ===========================================================================
# Public entry point
# ===========================================================================

async def scrape_greenhouse(target_url: str) -> list[dict]:
    """
    Fetch all open Israel-based jobs for a Greenhouse-hosted company,
    including full plain-text descriptions via concurrent double-fetch.

    Args:
        target_url: Board token slug, e.g. "similarweb"

    Returns:
        List of fully-populated job dicts (title, url, location, job_hash,
        description). Always returns [] on fatal error — never raises.

    PHASE 1 — single list request → filter to Israel jobs
    PHASE 2 — concurrent description fetches via asyncio.gather()
              bounded by DESC_CONCURRENCY semaphore
    CLEANUP  — strip internal `_gh_id` key before returning
    """
    board_token = target_url.strip().strip("/")

    if not board_token:
        print("[Greenhouse] ERROR: board token is empty.")
        return []

    print(f"[Greenhouse] Phase 1 — fetching job list for board='{board_token}'...")

    # --- Phase 1: fetch job list ---
    # One shared ClientSession for all requests in this scrape run.
    # aiohttp reuses the underlying TCP connection across all gather() calls —
    # much more efficient than opening a new session per description fetch.
    async with aiohttp.ClientSession() as session:

        try:
            list_url = GH_LIST_API.format(board_token=board_token)
            async with session.get(
                list_url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

        except aiohttp.ClientResponseError as e:
            print(f"[Greenhouse] Phase 1 HTTP {e.status} for board='{board_token}': {e.message}"
                  + (" (wrong board token?)" if e.status == 404 else ""))
            return []
        except aiohttp.ClientConnectionError as e:
            print(f"[Greenhouse] Phase 1 connection error for board='{board_token}': {e}")
            return []
        except asyncio.TimeoutError:
            print(f"[Greenhouse] Phase 1 timeout for board='{board_token}'.")
            return []
        except Exception as e:
            print(f"[Greenhouse] Phase 1 unexpected error for board='{board_token}': {e}")
            return []

        if not isinstance(data, dict) or "jobs" not in data:
            print(f"[Greenhouse] Phase 1 unexpected response shape for board='{board_token}'.")
            return []

        raw_jobs = data["jobs"]
        print(f"[Greenhouse] {len(raw_jobs)} total job(s). Filtering for Israel...")

        # Filter + map to partial dicts (no description yet)
        il_jobs: list[dict] = []
        for job in raw_jobs:
            location_name = (job.get("location", {}).get("name") or "")
            if not _is_israel(location_name):
                continue
            mapped = _map_job_from_list(job)
            if mapped:
                il_jobs.append(mapped)

        print(f"[Greenhouse] {len(il_jobs)} Israel job(s) found. "
              f"Phase 2 — fetching descriptions (concurrency={DESC_CONCURRENCY})...")

        # --- Phase 2: concurrent description fetches ---
        if il_jobs:
            semaphore = asyncio.Semaphore(DESC_CONCURRENCY)
            await asyncio.gather(*[
                _fetch_description(session, semaphore, board_token, job)
                for job in il_jobs
            ])
            # gather() modifies each job dict in-place via _fetch_description.
            # No need to collect return values — il_jobs already has the updates.

    # Strip the internal _gh_id key — workers and DB don't need it
    for job in il_jobs:
        job.pop("_gh_id", None)

    print(f"[Greenhouse] Done. {len(il_jobs)} fully-enriched job(s) for board='{board_token}'.")
    return il_jobs