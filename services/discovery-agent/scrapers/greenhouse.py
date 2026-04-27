"""
scrapers/greenhouse.py — Generic async scraper for the Greenhouse ATS public API.

Works for ANY company hosted on Greenhouse job boards.
The company board token (slug) is stored in TargetSite.base_url,
so adding a new Greenhouse company = one new DB row, zero code changes.

Discovered from: Similarweb's careers page HTML contained an inline JSON
blob on line 946 with entries like:
    {"id":237336,"title":"Big Data Analyst",
     "link":"https://job-boards.greenhouse.io/similarweb/jobs/6897277",
     "location":"Tel Aviv, Israel","department":"dev"}

This reveals Greenhouse's fully public Job Board API:
    GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
        ?content=true     ← include full job description
        &live=true        ← only active postings

Public API (the only symbol worker.py needs):
    await scrape_greenhouse(target_url: str) -> list[dict]

`target_url` format (stored in TargetSite.base_url):
    The board token — the slug that appears in the Greenhouse URL.
    e.g.  "similarweb"  →  boards-api.greenhouse.io/v1/boards/similarweb/jobs

    To find any company's board token:
      Option A: Look at job URLs on their careers page.
                job-boards.greenhouse.io/{THIS_PART}/jobs/{id}
      Option B: Check the page source for boards-api.greenhouse.io or
                boards.greenhouse.io mentions.
      Option C: Search  site:job-boards.greenhouse.io "company name"

Each returned dict has exactly these keys (matching the Job model schema):
    title     : str  — job.title
    url       : str  — job.absolute_url  (the public Greenhouse job page)
    location  : str  — job.location.name
    job_hash  : str  — str(job.id)  (numeric, e.g. "6897277")

Only Israel-based jobs are returned.
Israel is detected by checking (in priority order):
    1. "israel" in location.name (case-insensitive)
    2. "tel aviv" / other Israeli city names in location.name

WHY NO TOKEN?
Greenhouse's job board API is fully public — the same data your browser
fetches when rendering any company's Greenhouse careers page.

Dependencies:
    pip install aiohttp
"""

import asyncio

import aiohttp

# ===========================================================================
# API
# ===========================================================================

# Greenhouse has two API base URLs depending on the company's plan/setup.
# boards-api is the standard REST API. We try this first.
# If a company uses the older embed API, the board_token is still the same.
GREENHOUSE_API = (
    "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    "?content=true"      # include job descriptions (we don't use them but
                         # some ATS scrapers need them for dedup hashing)
)

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

# Israeli location keywords for fallback detection.
# Ordered roughly by population size so the most common matches
# are checked first (minor optimisation).
_IL_KEYWORDS = (
    "israel",
    "tel aviv",
    "tel-aviv",
    "tlv",
    "herzliya",
    "raanana",
    "ra'anana",
    "rishon",
    "petah tikva",
    "petach tikva",
    "haifa",
    "beer sheva",
    "be'er sheva",
    "netanya",
    "rehovot",
    "kfar saba",
)


# ===========================================================================
# Israel detection
# ===========================================================================

def _is_israel(job: dict) -> bool:
    """
    Return True if this job is based in Israel.

    Greenhouse stores location as a dict: {"name": "Tel Aviv, Israel"}.
    Some companies use "Israel" standalone, others use "Tel Aviv, Israel",
    others use just "TLV". We check all known patterns.
    """
    location_name = (
        job.get("location", {}).get("name") or ""
    ).lower()

    return any(kw in location_name for kw in _IL_KEYWORDS)


# ===========================================================================
# Field mapping
# ===========================================================================

def _map_job(job: dict) -> dict | None:
    """
    Convert one Greenhouse API job object into our internal schema dict.

    Returns None if the job is missing the minimum required fields,
    so the caller can skip it without crashing.

    FIELD NOTES:
      title        — plain string, e.g. "Big Data Analyst"
      absolute_url — the canonical public Greenhouse job page URL
                     e.g. https://job-boards.greenhouse.io/similarweb/jobs/6897277
      location.name— human-readable location string
      id           — numeric job ID; we convert to string for job_hash
    """
    title = (job.get("title") or "").strip()
    url   = (job.get("absolute_url") or "").strip()

    if not title or not url:
        return None

    location = (
        job.get("location", {}).get("name") or ""
    ).strip()

    job_hash = str(job.get("id") or "").strip()

    return {
        "title":    title,
        "url":      url,
        "location": location,
        "job_hash": job_hash,
    }


# ===========================================================================
# Public entry point
# ===========================================================================

async def scrape_greenhouse(target_url: str) -> list[dict]:
    """
    Fetch all open Israel-based jobs for a Greenhouse-hosted company.

    Args:
        target_url: The board token stored in TargetSite.base_url.
                    e.g. "similarweb"

    Returns:
        List of job dicts [{title, url, location, job_hash}, ...].
        Always returns a list (never raises) so the worker acks/nacks cleanly.

    PAGINATION:
        Greenhouse's board API returns ALL active jobs for the board in a
        single response under the "jobs" key — it is not paginated.
        We filter for Israel client-side after receiving the full list.

    RESPONSE SHAPE:
        {
          "jobs": [ {job}, {job}, ... ],
          "meta": { "total": N }
        }
    """
    board_token = target_url.strip().strip("/")

    if not board_token:
        print("[Greenhouse] ERROR: target_url (board token) is empty. Returning [].")
        return []

    api_url = GREENHOUSE_API.format(board_token=board_token)
    print(f"[Greenhouse] Fetching jobs for board='{board_token}'...")

    # --- Fetch ---
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                headers=_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

    except aiohttp.ClientResponseError as e:
        print(
            f"[Greenhouse] HTTP {e.status} for board='{board_token}': {e.message}."
            + (" Board token may be wrong." if e.status == 404 else "")
        )
        return []
    except aiohttp.ClientConnectionError as e:
        print(f"[Greenhouse] Connection error for board='{board_token}': {e}")
        return []
    except asyncio.TimeoutError:
        print(f"[Greenhouse] Timeout for board='{board_token}'.")
        return []
    except Exception as e:
        print(f"[Greenhouse] Unexpected error for board='{board_token}': {e}")
        return []

    # --- Validate response shape ---
    if not isinstance(data, dict) or "jobs" not in data:
        print(
            f"[Greenhouse] Unexpected response shape for board='{board_token}': "
            f"expected {{\"jobs\": [...]}}, got {type(data).__name__}."
        )
        return []

    raw_jobs = data["jobs"]
    total    = data.get("meta", {}).get("total", len(raw_jobs))
    print(f"[Greenhouse] {total} total job(s) received. Filtering for Israel...")

    # --- Filter + map ---
    all_jobs: list[dict] = []

    for job in raw_jobs:
        if not _is_israel(job):
            continue
        mapped = _map_job(job)
        if mapped is None:
            continue
        all_jobs.append(mapped)

    print(
        f"[Greenhouse] Done. {len(all_jobs)} Israel-based job(s) found "
        f"for board='{board_token}'."
    )
    return all_jobs