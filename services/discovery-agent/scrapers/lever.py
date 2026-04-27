"""
scrapers/lever.py — Generic async scraper for the Lever ATS public API.

Works for ANY company hosted on Lever — not just Cloudinary.
The company slug (e.g. "cloudinary") is stored in TargetSite.base_url,
so adding a new Lever company = one new DB row, zero code changes.

Public API (the only symbol worker.py needs):
    await scrape_lever(target_url: str) -> list[dict]

`target_url` format (stored in TargetSite.base_url):
    Just the company slug as it appears in the Lever URL.
    e.g.  "cloudinary"   →  api.lever.co/v0/postings/cloudinary?mode=json

    To find the slug for any company:
      1. Go to their careers page
      2. Open DevTools → Network tab
      3. Look for a request to api.lever.co/v0/postings/{SLUG}
      OR search:  site:jobs.lever.co "company name"

Each returned dict has exactly these keys (matching the Job model schema):
    title     : str  — posting.text
    url       : str  — posting.hostedUrl  (the public job page)
    location  : str  — posting.categories.location
    job_hash  : str  — posting.id  (UUID string, e.g. "a1b2c3d4-...")

Only Israel-based postings are returned.
Israel is detected by checking (in priority order):
    1. posting.country == "IL"          (explicit country code, most reliable)
    2. "israel" in categories.location  (location string fallback)
    3. "tel aviv" in categories.location

WHY NO TOKEN?
Lever's v0 API is fully public — no authentication required.
The same endpoint your browser hits when loading a company's jobs page.

Dependencies:
    pip install aiohttp
"""

import asyncio

import aiohttp

# ===========================================================================
# API
# ===========================================================================

LEVER_API_TEMPLATE = "https://api.lever.co/v0/postings/{slug}?mode=json"

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

# Strings we look for inside the location field (case-insensitive) when the
# top-level `country` field is absent or empty — which happens on older
# Lever integrations that pre-date the country field.
_IL_LOCATION_KEYWORDS = ("israel", "tel aviv", "tel-aviv", "tlv", "herzliya",
                          "raanana", "ra'anana", "petah tikva", "beer sheva")


# ===========================================================================
# Israel detection
# ===========================================================================

def _is_israel(posting: dict) -> bool:
    """
    Return True if this job posting is based in Israel.

    Priority:
      1. posting.country == "IL"             — explicit, always trust this
      2. keyword match in categories.location — fallback for older postings

    WHY TWO CHECKS?
    Lever added the top-level `country` field relatively recently. Postings
    created before that field existed (or companies that haven't re-saved
    their postings) won't have it set. The location-string fallback catches
    those without false-positives on generic "Remote" postings.
    """
    # Primary — explicit country code
    country = (posting.get("country") or "").strip().upper()
    if country == "IL":
        return True

    # Fallback — location string keyword match
    location = (
        posting.get("categories", {}).get("location") or ""
    ).lower()
    return any(kw in location for kw in _IL_LOCATION_KEYWORDS)


# ===========================================================================
# Field mapping
# ===========================================================================

def _map_posting(posting: dict) -> dict | None:
    """
    Convert one Lever API posting object into our internal job schema.

    Returns None if the posting is missing the minimum required fields
    (title + url), so the caller can skip it cleanly.

    FIELD NOTES:
      text        — the job title (Lever calls it "text", not "title")
      hostedUrl   — the canonical public job page URL
                    (prefer over applyUrl which goes straight to application form)
      id          — a UUID; we use it as job_hash for deduplication
      categories.location — human-readable location string
    """
    title    = (posting.get("text") or "").strip()
    url      = (posting.get("hostedUrl") or "").strip()

    if not title or not url:
        return None

    location = (
        posting.get("categories", {}).get("location") or ""
    ).strip()

    job_hash = (posting.get("id") or "").strip()

    return {
        "title":    title,
        "url":      url,
        "location": location,
        "job_hash": job_hash,
    }


# ===========================================================================
# Public entry point
# ===========================================================================

async def scrape_lever(target_url: str) -> list[dict]:
    """
    Fetch all open Israel-based postings for a Lever-hosted company.

    Args:
        target_url: The company slug stored in TargetSite.base_url.
                    e.g. "cloudinary"

    Returns:
        List of job dicts [{title, url, location, job_hash}, ...].
        Returns an empty list (never raises) so the worker acks/nacks
        cleanly based on return value.

    PAGINATION:
        Lever's v0 API with ?mode=json returns ALL postings in one
        response — it is not paginated. We filter for Israel client-side.
    """
    slug = target_url.strip().strip("/")

    if not slug:
        print("[Lever] ERROR: target_url (company slug) is empty. Returning [].")
        return []

    api_url = LEVER_API_TEMPLATE.format(slug=slug)
    print(f"[Lever] Fetching postings for company slug='{slug}'...")

    # --- Fetch ---
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                headers=_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                postings: list[dict] = await resp.json(content_type=None)

    except aiohttp.ClientResponseError as e:
        print(
            f"[Lever] HTTP {e.status} for slug='{slug}': {e.message}. "
            f"{'Slug may be wrong or company moved ATS.' if e.status == 404 else ''}"
        )
        return []
    except aiohttp.ClientConnectionError as e:
        print(f"[Lever] Connection error for slug='{slug}': {e}")
        return []
    except asyncio.TimeoutError:
        print(f"[Lever] Request timed out for slug='{slug}'.")
        return []
    except Exception as e:
        print(f"[Lever] Unexpected error for slug='{slug}': {e}")
        return []

    if not isinstance(postings, list):
        print(
            f"[Lever] Unexpected response shape for slug='{slug}': "
            f"expected JSON array, got {type(postings).__name__}."
        )
        return []

    print(f"[Lever] {len(postings)} total postings received. Filtering for Israel...")

    # --- Filter + map ---
    all_jobs: list[dict] = []

    for posting in postings:
        if not _is_israel(posting):
            continue
        job = _map_posting(posting)
        if job is None:
            continue
        all_jobs.append(job)

    print(
        f"[Lever] Done. {len(all_jobs)} Israel-based posting(s) found "
        f"for slug='{slug}'."
    )
    return all_jobs