"""Unit tests for infrastructure/db/sync_plan.py (no database needed)."""

from datetime import datetime, timedelta, timezone

from infrastructure.db.sync_plan import (
    STALE_AFTER,
    ExistingJob,
    content_hash,
    job_key,
    plan_sync,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def scraped(job_hash, title="Backend Developer", url=None, location="Tel Aviv", description="Python"):
    return {
        "job_hash": job_hash,
        "title": title,
        "url": url or f"https://example.com/jobs/{job_hash}",
        "location": location,
        "description": description,
    }


def stored(row_id, job_hash, title="Backend Developer", location="Tel Aviv", description="Python",
           last_seen=NOW - timedelta(days=1), closed_at=None, url=None):
    return ExistingJob(
        id=row_id,
        job_hash=job_hash,
        url=url or f"https://example.com/jobs/{job_hash}",
        title=title,
        location=location,
        description=description,
        content_hash=content_hash(title, location, description),
        last_seen=last_seen,
        closed_at=closed_at,
    )


def test_jobs_sharing_one_careers_url_are_all_kept():
    # OurCrowd case: Comeet's url_active_page was the same generic page for every position.
    same_url = "https://www.ourcrowd.com/careers"
    jobs = [scraped("9E.171", "VP Finance", same_url),
            scraped("9E.172", "Investment Analyst", same_url),
            scraped("9E.173", "Backend Developer", same_url)]
    plan = plan_sync([], jobs, NOW)
    assert [j["title"] for j in plan.inserts] == ["VP Finance", "Investment Analyst", "Backend Developer"]


def test_unchanged_job_is_only_stamped_as_seen():
    plan = plan_sync([stored(1, "a")], [scraped("a")], NOW)
    assert plan.seen_ids == [1]
    assert plan.inserts == [] and plan.updates == [] and plan.close_ids == []


def test_edited_description_is_written_back_with_a_new_hash():
    plan = plan_sync([stored(1, "a", description="Python")], [scraped("a", description="Python, Go")], NOW)
    (row_id, changes), = plan.updates
    assert row_id == 1
    assert changes["description"] == "Python, Go"
    assert changes["content_hash"] == content_hash("Backend Developer", "Tel Aviv", "Python, Go")


def test_empty_description_never_wipes_a_stored_one():
    plan = plan_sync([stored(1, "a", description="5 years of Java")], [scraped("a", description="")], NOW)
    assert plan.updates == []


def test_missing_job_is_closed_after_a_healthy_scrape():
    existing = [stored(i, f"j{i}") for i in range(1, 11)]
    plan = plan_sync(existing, [scraped(f"j{i}") for i in range(1, 10)], NOW)   # j10 is gone
    assert plan.healthy
    assert plan.close_ids == [10]


def test_partial_scrape_closes_nothing():
    existing = [stored(i, f"j{i}") for i in range(1, 11)]
    plan = plan_sync(existing, [scraped("j1"), scraped("j2")], NOW)            # 2 of 10 came back
    assert not plan.healthy
    assert plan.close_ids == []
    assert "partial scrape" in plan.note


def test_partial_scrape_still_closes_jobs_not_seen_for_a_week():
    existing = [stored(i, f"j{i}") for i in range(1, 11)]
    existing[9] = stored(10, "j10", last_seen=NOW - STALE_AFTER - timedelta(hours=1))
    plan = plan_sync(existing, [scraped("j1")], NOW)
    assert plan.close_ids == [10]


def test_empty_scrape_never_closes_fresh_jobs():
    plan = plan_sync([stored(1, "a"), stored(2, "b")], [], NOW)
    assert not plan.healthy
    assert plan.close_ids == []


def test_small_site_can_shrink_a_lot():
    existing = [stored(1, "a"), stored(2, "b"), stored(3, "c")]
    plan = plan_sync(existing, [scraped("a")], NOW)
    assert plan.healthy
    assert sorted(plan.close_ids) == [2, 3]


def test_closed_job_that_comes_back_is_reopened():
    plan = plan_sync([stored(1, "a", closed_at=NOW - timedelta(days=3))], [scraped("a")], NOW)
    assert plan.reopen_ids == [1] and plan.seen_ids == [1]


def test_already_closed_jobs_are_not_closed_again():
    existing = [stored(1, "a"), stored(2, "b", closed_at=NOW - timedelta(days=30))]
    plan = plan_sync(existing, [scraped("a")], NOW)
    assert plan.close_ids == []


def test_missing_ats_id_falls_back_to_a_stable_url_key():
    url = "https://careers.checkpoint.com/index.php?m=cpcareers&a=show&joborderid=123"
    assert job_key("", url) == job_key("", url)
    assert job_key("", url).startswith("url:")
    assert job_key("123", url) == "123"


def test_items_without_title_or_url_are_skipped():
    plan = plan_sync([], [{"title": "", "url": "x"}, {"title": "QA", "url": ""}, scraped("a")], NOW)
    assert plan.skipped == 2 and len(plan.inserts) == 1


def test_naive_datetimes_from_sqlite_are_handled():
    naive_old = (NOW - timedelta(days=30)).replace(tzinfo=None)
    existing = [stored(i, f"j{i}", last_seen=naive_old) for i in range(1, 11)]
    plan = plan_sync(existing, [scraped("j1")], NOW.replace(tzinfo=None))
    assert sorted(plan.close_ids) == list(range(2, 11))   # all stale, so closed despite the partial scrape
