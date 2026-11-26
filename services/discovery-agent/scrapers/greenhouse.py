"""
scrapers/greenhouse.py — Greenhouse ATS scraper (one request per board).

Strategy:
    GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

    Greenhouse's Job Board API docs: with ?content=true the LIST endpoint
    returns every job's `content` (the description), plus `offices` and
    `departments`. So one request per board is enough. The old version
    fetched each Israel job again (1 + N requests); that's gone.

    `content` is HTML-entity-encoded (&lt;p&gt; instead of <p>), per the
    same docs. It must be unescaped before stripping tags, otherwise the
    tags are stored as text. common.html_to_text() does both.

Public API:
    await scrape_greenhouse(target_url: str) -> list[dict]

Return schema (one dict per job):
    title       : str  — job.title
    url         : str  — job.absolute_url
    location    : str  — job.location.name
    job_hash    : str  — str(job.id)
    description : str  — plain text from job.content

Israel filter: location.name OR any office name/location. A job listed as
"Hybrid" or "Multiple locations" with a Tel Aviv office is kept.

Dependencies:
    pip install aiohttp beautifulsoup4 lxml
"""

import asyncio

import aiohttp

from scrapers.common import html_to_text, is_israel_location

# ===========================================================================
# API endpoint
# ===========================================================================

GH_LIST_API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"

# Big boards (Cloudflare, Okta, Rubrik) return several MB with content=true.
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)

_HEADERS = {
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


# ===========================================================================
# Israel filter
# ===========================================================================

def _is_israel_job(job: dict) -> bool:
    location_name = ((job.get("location") or {}).get("name") or "")
    if is_israel_location(location_name):
        return True
    for office in job.get("offices") or []:
        if is_israel_location(f"{office.get('name') or ''} {office.get('location') or ''}"):
            return True
    return False


# ===========================================================================
# Field mapping
# ===========================================================================

def _map_job(job: dict) -> dict | None:
    """
    Build our job dict from one entry of the list response.
    Returns None if the minimum required fields are missing.
    """
    title = (job.get("title") or "").strip()
    url   = (job.get("absolute_url") or "").strip()

    if not title or not url:
        return None

    return {
        "title":       title,
        "url":         url,
        "location":    ((job.get("location") or {}).get("name") or "").strip(),
        "job_hash":    str(job.get("id") or "").strip(),
        "description": html_to_text(job.get("content") or ""),
    }


# ===========================================================================
# Public entry point
# ===========================================================================

async def scrape_greenhouse(target_url: str) -> list[dict]:
    """
    Fetch all open Israel-based jobs for a Greenhouse-hosted company,
    descriptions included, in a single request.

    Args:
        target_url: Board token slug, e.g. "similarweb"

    Returns:
        List of job dicts (title, url, location, job_hash, description).
        Always returns [] on fatal error — never raises.
    """
    board_token = target_url.strip().strip("/")

    if not board_token:
        print("[Greenhouse] ERROR: board token is empty.")
        return []

    print(f"[Greenhouse] Fetching jobs (with content) for board='{board_token}'...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GH_LIST_API.format(board_token=board_token),
                headers=_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

    except aiohttp.ClientResponseError as e:
        print(f"[Greenhouse] HTTP {e.status} for board='{board_token}': {e.message}"
              + (" (wrong board token?)" if e.status == 404 else ""))
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

    if not isinstance(data, dict) or "jobs" not in data:
        print(f"[Greenhouse] Unexpected response shape for board='{board_token}'.")
        return []

    raw_jobs = data["jobs"]
    print(f"[Greenhouse] {len(raw_jobs)} total job(s). Filtering for Israel...")

    il_jobs: list[dict] = []
    for job in raw_jobs:
        if not _is_israel_job(job):
            continue
        mapped = _map_job(job)
        if mapped:
            il_jobs.append(mapped)

    print(f"[Greenhouse] Done. {len(il_jobs)} Israel job(s) for board='{board_token}'.")
    return il_jobs
