"""run_scan.scan_all(): the part of the cloud scan that needs no database."""

import asyncio

import run_scan


def _site(site_id, name="comeet", url="x"):
    return {"id": site_id, "name": name, "url": url, "company": f"Company {site_id}"}


def test_one_failing_site_does_not_stop_the_others():
    async def ok(url):
        return [{"title": "QA", "url": url, "job_hash": "1"}]

    async def broken(url):
        raise RuntimeError("Page 1 returned HTTP 403")

    sites = [_site(1, "comeet", "a"), _site(2, "checkpoint", "b"), _site(3, "workday", "c")]
    results = asyncio.run(run_scan.scan_all(sites, {"comeet": ok, "checkpoint": broken}, concurrency=2))

    by_id = {site["id"]: (jobs, error) for site, jobs, error in results}
    assert by_id[1] == ([{"title": "QA", "url": "a", "job_hash": "1"}], "")
    assert by_id[2][0] is None and "403" in by_id[2][1]
    assert by_id[3][0] is None and "no scraper" in by_id[3][1]


def test_concurrency_is_capped():
    running = 0
    peak = 0

    async def slow(url):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return []

    asyncio.run(run_scan.scan_all([_site(i) for i in range(10)], {"comeet": slow}, concurrency=3))
    assert peak == 3


def test_the_registry_covers_every_scraper_in_the_seed_list():
    from test_repo_hygiene import KNOWN_SCRAPERS
    assert set(run_scan.SCRAPERS) == KNOWN_SCRAPERS
