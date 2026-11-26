"""
scrapers/checkpoint.py — aiohttp + BeautifulSoup scraper for Checkpoint careers (Israel).

Robustness upgrades over previous version:
  1. Retry with exponential backoff  — distinguishes a soft-block (empty 200)
     from a genuine end-of-results by retrying up to MAX_RETRIES times before
     accepting an empty page as final.
  2. Persistent cookie jar           — aiohttp.CookieJar carries session cookies
     across all page requests, exactly like a real browser session would.
  3. Smarter stop logic              — requires CONSECUTIVE_EMPTY_STOP consecutive
     empty pages before stopping, so one flaky response doesn't kill the run.
  4. Cache-Control / Pragma headers  — prevents the server returning a cached
     empty page from a previous blocked session.

Public API:
    await scrape_checkpoint(target_url: str) -> list[dict]

Each dict: {title, url, location, job_hash}

Dependencies:
    pip install aiohttp beautifulsoup4 lxml
"""

import asyncio
import random
import re
from urllib.parse import urlparse, parse_qs, urljoin

import aiohttp
from bs4 import BeautifulSoup

# ===========================================================================
# Selectors  (update here if Checkpoint changes their DOM)
# ===========================================================================

CP_CARD_SELECTOR = "div.position"
CP_LINK_SELECTOR = "a[href*='joborderid']"
CP_LOCATION_SELECTOR = "div.posInfo"

_HREF_BLOCKLIST: tuple[str, ...] = (
    "whatsapp", "linkedin", "facebook", "twitter", "mailto",
)

# ===========================================================================
# Pagination & retry config
# ===========================================================================

CP_BASE_URL = "https://careers.checkpoint.com"
CP_SEARCH_URL = (
    "https://careers.checkpoint.com/index.php"
    "?q="
    "&module=cpcareers"
    "&a=search"
    "&fa%5B%5D=country_ss%3AIsrael"
    "&sort="
    "&start={offset}"
)

CP_PAGE_STRIDE = 10
CP_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# How many times to retry a page that came back empty before treating it
# as a genuine end-of-results. Each retry waits longer (exponential backoff).
MAX_RETRIES = 3
RETRY_BASE_DELAY = 4.0      # seconds — first retry waits ~4s, second ~8s, third ~16s

# How many consecutive empty-after-retry pages must occur before we stop.
# 1 = stop on first confirmed empty page (strict, may stop early on flaky servers)
# 2 = require two in a row (more robust, costs one extra request at the true end)
CONSECUTIVE_EMPTY_TO_STOP = 2

# ===========================================================================
# User-Agents  (rotated once per run — not per page)
# ===========================================================================

_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
)


def _build_headers(ua: str, referer: str) -> dict[str, str]:
    """
    Full realistic browser header set for one request.

    Cache-Control + Pragma tell the server (and any intermediate proxy)
    not to serve a cached response — important because a cached empty page
    from a previous blocked session looks identical to a real empty page.
    """
    return {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9,he;q=0.8",
        "Accept-Encoding":           "gzip, deflate, br",
        "Referer":                   referer,
        "DNT":                       "1",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control":             "no-cache",
        "Pragma":                    "no-cache",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "same-origin",
        "Sec-Fetch-User":            "?1",        # signals a user-initiated navigation
    }


# ===========================================================================
# Parsing helpers  (pure functions — no I/O)
# ===========================================================================

def _is_job_link(href: str) -> bool:
    return not any(blocked in href for blocked in _HREF_BLOCKLIST)


def _extract_job_hash(full_url: str) -> str:
    try:
        params = parse_qs(urlparse(full_url).query)
        if "joborderid" in params:
            return params["joborderid"][0]
    except Exception:
        pass
    match = re.search(r"joborderid[=:](\d+)", full_url, re.IGNORECASE)
    return match.group(1) if match else ""


def _parse_cards(html: str) -> list[dict]:
    """
    Parse one page of HTML into job dicts.
    Pure function — pass HTML string in, get list of dicts out.
    """
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(CP_CARD_SELECTOR)
    jobs: list[dict] = []

    for card in cards:
        anchor = None
        for candidate in card.select(CP_LINK_SELECTOR):
            href = candidate.get("href", "")
            if _is_job_link(href):
                anchor = candidate
                break

        if anchor is None:
            continue

        title = anchor.get_text(strip=True)
        href  = anchor.get("href", "").strip()

        if not title or not href:
            continue

        full_url = urljoin(CP_BASE_URL, href)

        location = ""
        loc_el = card.select_one(CP_LOCATION_SELECTOR)
        if loc_el:
            location = loc_el.get_text(strip=True)

        jobs.append({
            "title":    title,
            "url":      full_url,
            "location": location,
            "job_hash": _extract_job_hash(full_url),
        })

    return jobs


# ===========================================================================
# Fetch with retry + exponential backoff
# ===========================================================================

async def _fetch_with_retry(
    session: aiohttp.ClientSession,
    offset:  int,
    ua:      str,
    referer: str,
) -> tuple[str, bool]:
    """
    Fetch one page and retry up to MAX_RETRIES times if it comes back empty.

    Returns:
        (html, is_confirmed_empty)
        is_confirmed_empty = True only if ALL attempts returned zero cards.

    WHY RETRY ON EMPTY (not just on HTTP error)?
    Checkpoint returns HTTP 200 even when soft-blocking — the body is just
    a stripped HTML shell with no job cards. We can't tell a real end-of-
    results from a transient block without trying again after a pause.
    If at least one retry returns cards, the block was transient and we
    continue. Only if every attempt returns empty do we trust it as genuine.
    """
    url = CP_SEARCH_URL.format(offset=offset)

    for attempt in range(1, MAX_RETRIES + 1):
        headers = _build_headers(ua, referer)

        try:
            async with session.get(
                url,
                headers=headers,
                timeout=CP_REQUEST_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                resp.raise_for_status()
                raw      = await resp.read()
                encoding = resp.charset or "utf-8"
                html     = raw.decode(encoding, errors="replace")

        except aiohttp.ClientResponseError as e:
            # Hard HTTP error — don't retry, let caller handle
            raise

        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(f"[Checkpoint]   ⚠ Request error (attempt {attempt}/{MAX_RETRIES}): {e}. "
                  f"Retrying in {wait:.0f}s...")
            await asyncio.sleep(wait)
            continue

        # Got HTML — check if it has any cards
        cards = _parse_cards(html)
        if cards:
            # Real content — return immediately, no more retries needed
            return html, False

        # Empty page — might be a soft block, might be genuine end
        if attempt < MAX_RETRIES:
            wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(f"[Checkpoint]   ⚠ Empty page at offset={offset} "
                  f"(attempt {attempt}/{MAX_RETRIES}). "
                  f"Possible soft-block. Retrying in {wait:.0f}s...")
            await asyncio.sleep(wait)
        else:
            print(f"[Checkpoint]   All {MAX_RETRIES} attempts returned empty "
                  f"at offset={offset}. Treating as confirmed empty.")

    return html, True   # confirmed empty after all retries


# ===========================================================================
# Public entry point
# ===========================================================================

async def scrape_checkpoint(target_url: str) -> list[dict]:
    """
    Fetch ALL Checkpoint Israel job postings across every paginated page.

    PAGINATION:   offset = 0, 10, 20 … (CP_PAGE_STRIDE = 10)

    STOP CONDITIONS (in priority order):
        1. HTTP error on page 1       → raise (worker nacks + redelivers)
        2. HTTP error on page N>1     → break, return what we have
        3. CONSECUTIVE_EMPTY_TO_STOP confirmed-empty pages in a row
           → genuine end of results, stop cleanly

    COOKIE JAR:
        aiohttp.CookieJar() is passed to ClientSession so cookies set by
        the server (session ID, CSRF tokens) persist across all page requests
        in this run — exactly like a real browser maintaining a session.
    """
    all_jobs:  list[dict] = []
    seen_urls: set[str]   = set()
    pages_visited   = 0
    consecutive_empty = 0

    ua      = random.choice(_USER_AGENTS)
    referer = target_url

    print(f"[Checkpoint] Starting scrape. UA: {ua[:60]}...")

    # CookieJar persists cookies across all requests in this session.
    # unsafe=True allows cookies on IP addresses (needed for some redirects).
    cookie_jar = aiohttp.CookieJar(unsafe=True)

    async with aiohttp.ClientSession(cookie_jar=cookie_jar) as session:

        # --- Warm-up request ---
        # Visit the base careers page first (no offset) to collect any session
        # cookies the server sets before the search results page.
        # A real browser always lands on the main page before paginating.
        try:
            print(f"[Checkpoint] Warming up session (visiting base page)...")
            async with session.get(
                CP_BASE_URL,
                headers=_build_headers(ua, "https://www.google.com"),
                timeout=CP_REQUEST_TIMEOUT,
            ) as warm:
                _ = await warm.read()   # consume body to complete the request
            await asyncio.sleep(random.uniform(1.5, 3.0))
        except Exception as e:
            print(f"[Checkpoint] Warm-up failed (non-fatal): {e}")

        # --- Pagination loop ---
        offset = 0

        while True:
            print(f"[Checkpoint] → offset={offset}  (page {pages_visited + 1})")

            try:
                html, confirmed_empty = await _fetch_with_retry(
                    session, offset, ua, referer
                )
            except aiohttp.ClientResponseError as e:
                if offset == 0:
                    raise RuntimeError(
                        f"[Checkpoint] Page 1 returned HTTP {e.status}. "
                        "Site may be blocking or is down."
                    ) from e
                print(f"[Checkpoint] HTTP {e.status} at offset={offset}. "
                      f"Stopping and returning {len(all_jobs)} jobs collected so far.")
                break
            except Exception as e:
                if offset == 0:
                    raise RuntimeError(
                        f"[Checkpoint] Page 1 failed: {e}"
                    ) from e
                print(f"[Checkpoint] Error at offset={offset}: {e}. "
                      f"Stopping with {len(all_jobs)} jobs.")
                break

            if confirmed_empty:
                consecutive_empty += 1
                print(f"[Checkpoint] Confirmed empty page "
                      f"({consecutive_empty}/{CONSECUTIVE_EMPTY_TO_STOP}).")
                if consecutive_empty >= CONSECUTIVE_EMPTY_TO_STOP:
                    print("[Checkpoint] Scrape complete — end of results confirmed.")
                    break
                # Advance offset and try next page before giving up
                offset += CP_PAGE_STRIDE
                await asyncio.sleep(random.uniform(2.0, 4.0))
                continue

            # Got real cards — reset the consecutive-empty counter
            consecutive_empty = 0
            page_jobs = _parse_cards(html)
            pages_visited += 1
            referer = CP_SEARCH_URL.format(offset=offset)

            new_this_page = 0
            for job in page_jobs:
                if job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    all_jobs.append(job)
                    new_this_page += 1

            print(
                f"[Checkpoint]   {len(page_jobs)} cards, "
                f"{new_this_page} new unique jobs "
                f"(total: {len(all_jobs)})"
            )

            if new_this_page == 0:
                # Cards exist but all already seen → server is cycling results
                print("[Checkpoint] No new unique jobs. End of results.")
                break

            offset += CP_PAGE_STRIDE

            delay = random.uniform(1.5, 3.5)
            print(f"[Checkpoint] Waiting {delay:.1f}s...")
            await asyncio.sleep(delay)

    print(f"[Checkpoint] Finished. {len(all_jobs)} unique jobs, {pages_visited} page(s).")
    return all_jobs