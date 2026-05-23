"""
scrapers/lever.py — Generic async scraper for the Lever ATS public API.

DESCRIPTION STRATEGY — SINGLE FETCH (no double-fetch needed):
  Lever's v0 `?mode=json` list endpoint already returns the full description
  on every posting object. Two fields are available:
    descriptionPlain — pre-stripped plain text  ← preferred, use directly
    description      — raw HTML string          ← fallback, strip with BS4

  Unlike Greenhouse, there is NO additional data gained by fetching individual
  job endpoints. The individual endpoint (/v0/postings/{slug}/{id}) returns
  identical fields to the list. Double-fetching would cost N extra requests
  for zero benefit.

  Source: Lever's official postings API documentation + README examples.

Public API:
    await scrape_lever(target_url: str) -> list[dict]

`target_url` (stored in TargetSite.base_url):
    The company slug from the Lever URL.
    e.g. "cloudinary"  →  api.lever.co/v0/postings/cloudinary?mode=json

Return schema (one dict per job):
    title       : str  — posting.text
    url         : str  — posting.hostedUrl
    location    : str  — posting.categories.location
    job_hash    : str  — posting.id  (UUID)
    description : str  — posting.descriptionPlain  (or HTML-stripped fallback)

Only Israeli jobs are returned.

Dependencies:
    pip install aiohttp beautifulsoup4 lxml
"""

import asyncio

import aiohttp
from bs4 import BeautifulSoup

# ===========================================================================
# API
# ===========================================================================

LEVER_API = "https://api.lever.co/v0/postings/{slug}?mode=json"

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
# Israel location keywords (identical to greenhouse.py for consistency)
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


def _is_israel_posting(posting: dict) -> bool:
    """
    Two-layer Israel check:
      1. posting.country == "IL"         — explicit code, most reliable
      2. keyword match in location string — fallback for older postings
         that pre-date the country field
    """
    country = (posting.get("country") or "").strip().upper()
    if country == "IL":
        return True

    location = (posting.get("categories", {}).get("location") or "").lower()
    return any(kw in location for kw in _IL_KEYWORDS)


# ===========================================================================
# HTML → plain text  (used only when descriptionPlain is absent)
# ===========================================================================

def _strip_html(html: str) -> str:
    """
    Strip HTML tags from a Lever `description` field.

    This is a fallback path — Lever almost always populates `descriptionPlain`
    already. We only reach here if a posting has `description` but no
    `descriptionPlain`, which can happen on very old or manually-created postings.

    WHY lxml?
    Lever description HTML is well-formed (WYSIWYG editor output). lxml
    parses it correctly and is faster than html.parser.
    """
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)


# ===========================================================================
# Field mapping
# ===========================================================================

def _extract_description(posting: dict) -> str:
    """
    Extract the cleanest available description from a Lever posting.

    Priority:
      1. descriptionPlain — already plain text, no processing needed
      2. description      — HTML, strip with BeautifulSoup
      3. lists            — structured sections (role/requirements/etc.),
                            concatenated as a last resort
      4. ""               — empty if nothing is available

    WHY CHECK `lists` AS FALLBACK?
    Some companies write their entire job description inside `lists` (an array
    of {text, content} objects for sections like "About the Role", "Requirements")
    and leave `description` empty. Concatenating them gives usable content.
    """
    # Path 1 — pre-stripped plain text
    plain = (posting.get("descriptionPlain") or "").strip()
    if plain:
        return plain

    # Path 2 — strip HTML description
    html = (posting.get("description") or "").strip()
    if html:
        stripped = _strip_html(html)
        if stripped:
            return stripped

    # Path 3 — concatenate structured sections from `lists`
    sections = posting.get("lists") or []
    if sections:
        parts = []
        for section in sections:
            heading = (section.get("text") or "").strip()
            content = _strip_html(section.get("content") or "")
            if heading:
                parts.append(heading)
            if content:
                parts.append(content)
        combined = " ".join(parts).strip()
        if combined:
            return combined

    return ""


def _map_posting(posting: dict) -> dict | None:
    """
    Convert one Lever posting object to our internal job schema.
    Returns None if the minimum required fields (title + url) are missing.

    NO internal ID injection needed (unlike Greenhouse) because we extract
    all data including description from this single object — no second fetch.
    """
    title = (posting.get("text") or "").strip()
    url   = (posting.get("hostedUrl") or "").strip()

    if not title or not url:
        return None

    return {
        "title":       title,
        "url":         url,
        "location":    (posting.get("categories", {}).get("location") or "").strip(),
        "job_hash":    (posting.get("id") or "").strip(),
        "description": _extract_description(posting),
    }


# ===========================================================================
# Public entry point
# ===========================================================================

async def scrape_lever(target_url: str) -> list[dict]:
    """
    Fetch all open Israel-based jobs for a Lever-hosted company.

    Single HTTP request — description is included in the list response.
    No double-fetch, no concurrency management needed.

    Args:
        target_url: Company slug, e.g. "cloudinary"

    Returns:
        List of fully-populated job dicts (title, url, location, job_hash,
        description). Always returns [] on any error — never raises.
    """
    slug = target_url.strip().strip("/")

    if not slug:
        print("[Lever] ERROR: company slug is empty.")
        return []

    api_url = LEVER_API.format(slug=slug)
    print(f"[Lever] Fetching postings for slug='{slug}'...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                headers=_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                postings = await resp.json(content_type=None)

    except aiohttp.ClientResponseError as e:
        print(f"[Lever] HTTP {e.status} for slug='{slug}': {e.message}"
              + (" (wrong slug?)" if e.status == 404 else ""))
        return []
    except aiohttp.ClientConnectionError as e:
        print(f"[Lever] Connection error for slug='{slug}': {e}")
        return []
    except asyncio.TimeoutError:
        print(f"[Lever] Timeout for slug='{slug}'.")
        return []
    except Exception as e:
        print(f"[Lever] Unexpected error for slug='{slug}': {e}")
        return []

    if not isinstance(postings, list):
        print(f"[Lever] Unexpected response shape for slug='{slug}': "
              f"expected JSON array, got {type(postings).__name__}.")
        return []

    print(f"[Lever] {len(postings)} total postings. Filtering for Israel...")

    all_jobs: list[dict] = []
    for posting in postings:
        if not _is_israel_posting(posting):
            continue
        mapped = _map_posting(posting)
        if mapped is None:
            continue
        all_jobs.append(mapped)

    print(f"[Lever] Done. {len(all_jobs)} Israel job(s) for slug='{slug}'.")
    return all_jobs