"""
scrapers/comeet.py — Generic async scraper for the Comeet ATS public API.

Works for ANY company hosted on Comeet — not just one hardcoded employer.
The company identity is encoded in the `target_url` field stored in the DB,
so adding a new Comeet company requires only a new DB row, zero code changes.

Public API (the only symbol worker.py needs):
    await scrape_comeet(target_url: str) -> list[dict]

`target_url` format (stored in TargetSite.base_url):
    "<company_id>|<token>"
    e.g.  "41.00B|14B52C52C67790D3E1296BA37C20"

Each returned dict has exactly these keys (matching the Job model schema):
    title       : str  — job.name
    url         : str  — the position's own page on Comeet (see _position_url)
    location    : str  — job.location.name
    job_hash    : str  — job.uid
    description : str  — the `details` sections as plain text

Only Israel-based positions (location.country == "IL") are returned.

Dependencies:
    pip install aiohttp
"""

import asyncio

import aiohttp

from scrapers.common import html_to_text

# ===========================================================================
# API constants
# ===========================================================================

COMEET_API_TEMPLATE = (
    "https://www.comeet.co/careers-api/2.0/company/{company_id}/positions"
    "?token={token}"
    "&details=true"     # ← required to receive description fields;
                        #   omitting this returns positions without any
                        #   job description or requirements content
)

# Israel country code as used by Comeet's API.
TARGET_COUNTRY = "IL"

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


# ===========================================================================
# target_url parsing
# ===========================================================================

def _parse_target_url(target_url: str) -> tuple[str, str] | None:
    """
    Split "company_id|token" into its two parts.

    Returns (company_id, token) on success, None on bad format.

    WHY PIPE AS DELIMITER?
    Company IDs ("41.00B") and tokens (hex strings) never contain a pipe
    character, so splitting on "|" is unambiguous. It also makes the DB
    value human-readable at a glance without any encoding.
    """
    parts = target_url.split("|", maxsplit=1)
    if len(parts) != 2:
        return None

    company_id, token = parts[0].strip(), parts[1].strip()
    if not company_id or not token:
        return None

    return company_id, token


def _position_url(job: dict) -> str:
    """
    The position's own page.

    WHY NOT url_active_page FIRST?
    Comeet documents url_active_page as "either on the company's website or on
    the Recruit-hosted website". For some companies (OurCrowd in our DB) it is
    just their generic careers page, the same URL for every position, so the
    DB kept one job and dropped the rest. The hosted page is per position.
    Comeet is renaming url_comeet_hosted_page to url_recruit_hosted_page, so
    both names are read.
    """
    return (
        job.get("url_recruit_hosted_page")
        or job.get("url_comeet_hosted_page")
        or job.get("url_active_page")
        or ""
    ).strip()


# ===========================================================================
# Field mapping
# ===========================================================================

def _map_job(job: dict) -> dict | None:
    """
    Convert one Comeet API job object into our internal schema dict.

    DESCRIPTION FIELDS (available when &details=true is set):
      The response includes a `details` array of section objects.
      Each section has a `name` (e.g. "Job Description", "Requirements")
      and a `value` containing HTML content.
      We strip all HTML and concatenate sections into one plain-text string.

    Returns None if the job is missing the minimum required fields.
    """
    title = (job.get("name") or "").strip()

    url = _position_url(job)

    if not title or not url:
        return None

    location_obj = job.get("location") or {}
    location     = location_obj.get("name", "").strip()
    job_hash     = str(job.get("uid", "")).strip()

    # Extract description from the `details` array.
    # Each element: {"name": "Job Description", "value": "<p>...</p>", ...}
    # We concatenate all sections in order to form one complete description.
    details      = job.get("details") or []
    desc_parts   = []
    for section in details:
        heading = (section.get("name") or "").strip()
        html    = (section.get("value") or "").strip()
        if heading:
            desc_parts.append(heading)
        if html:
            desc_parts.append(html_to_text(html))
    description = "\n".join(desc_parts).strip()

    return {
        "title":       title,
        "url":         url,
        "location":    location,
        "job_hash":    job_hash,
        "description": description,
    }


# ===========================================================================
# Public entry point
# ===========================================================================

async def scrape_comeet(target_url: str) -> list[dict]:
    """
    Fetch all open Israel-based positions for a Comeet-hosted company.

    Args:
        target_url: "<company_id>|<token>" string from TargetSite.base_url.

    Returns:
        List of job dicts [{title, url, location, job_hash, description}, ...].
        Returns an empty list (never raises) so the worker can ack/nack
        based on the return value rather than catching exceptions here.

    WHY NO PAGINATION LOOP?
    The Comeet API returns ALL open positions for a company in a single
    response — it is not paginated. We filter client-side for Israel.
    If Comeet ever introduces pagination, add the loop here; the worker
    and factory need no changes.

    FILTERING:
        We check location.country == "IL" on every job object. This is
        more reliable than passing a country filter in the query string
        (undocumented parameters can silently break on API updates).
    """

    # --- Parse credentials from target_url ---
    parsed = _parse_target_url(target_url)
    if parsed is None:
        print(
            f"[Comeet] ERROR: target_url must be 'company_id|token', "
            f"got: {target_url!r}. Returning empty list."
        )
        return []

    company_id, token = parsed
    api_url = COMEET_API_TEMPLATE.format(company_id=company_id, token=token)
    print(f"[Comeet] Fetching positions for company_id={company_id!r}...")

    # --- Fetch ---
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                headers=_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()

                # content_type=None: Comeet may return "text/plain" or
                # "application/json" depending on version/config. We parse
                # whatever we get and let json.JSONDecodeError surface below
                # if the body truly isn't JSON.
                raw_jobs: list[dict] = await resp.json(content_type=None)

    except aiohttp.ClientResponseError as e:
        print(
            f"[Comeet] HTTP {e.status} for company_id={company_id!r}: {e.message}. "
            f"Check that the company_id and token are still valid."
        )
        return []
    except aiohttp.ClientConnectionError as e:
        print(f"[Comeet] Connection error for company_id={company_id!r}: {e}")
        return []
    except asyncio.TimeoutError:
        print(f"[Comeet] Request timed out for company_id={company_id!r}.")
        return []
    except Exception as e:
        print(f"[Comeet] Unexpected error fetching company_id={company_id!r}: {e}")
        return []

    if not isinstance(raw_jobs, list):
        print(
            f"[Comeet] Unexpected response shape for company_id={company_id!r}: "
            f"expected a JSON array, got {type(raw_jobs).__name__}."
        )
        return []

    print(f"[Comeet] {len(raw_jobs)} total positions received. Filtering for Israel...")

    # --- Filter + map ---
    all_jobs: list[dict] = []

    for job in raw_jobs:
        # Country filter — IL only
        location_obj = job.get("location") or {}
        country      = location_obj.get("country", "")
        if country != TARGET_COUNTRY:
            continue

        mapped = _map_job(job)
        if mapped is None:
            continue    # missing title or URL — skip silently

        all_jobs.append(mapped)

    print(
        f"[Comeet] Done. {len(all_jobs)} Israel-based job(s) found "
        f"for company_id={company_id!r}."
    )
    return all_jobs