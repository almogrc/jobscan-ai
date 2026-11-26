# fix/cloud-ready — review of feature/scraper-factory (25 Nov 2026)

Reviewed branch `feature/scraper-factory` at commit `c0503bf`. Each bug below was
confirmed against the original code: by running it for 1, 4, 6, 7 and 8, and by reading
it next to the vendor docs for the rest. The new worker and build tests fail on the old
code and pass on this one.

## Do this first: revoke the Firecrawl key

`services/discovery-agent/main.py` on **main** (the default branch of a public repo)
still has a Firecrawl API key in plain text (`fc-97…`), and it is in the history of
three branches. Deleting the line doesn't help, because the history stays public.
Revoke it in the Firecrawl dashboard and create a new one that lives only in `.env`.
(`amazon.py` also had browser session cookies from April; they're moved out of the code
below, and they have most likely expired.)

## Bugs fixed

| # | What went wrong | Fix |
|---|---|---|
| 1 | **Docker image couldn't build.** `pip install -r --no-cache-dir -r …` reads `--no-cache-dir` as the requirements file name. `CMD python worker.py` pointed at `/app/worker.py`, which doesn't exist. `aiohttp`, `beautifulsoup4` and `lxml` weren't in `requirements.txt` (saved as UTF-16 by PowerShell). No `.dockerignore`, so `.env` and `jobs.db` would have been copied into the image. | Fixed the pip line, `WORKDIR` + `CMD`, added the 3 packages, saved as UTF-8, added `.dockerignore`. |
| 2 | **Would never reach real Pub/Sub.** `producer.py` and `worker.py` set `PUBSUB_EMULATOR_HOST=localhost:8085` whenever it isn't set, so on Cloud Run every call goes to localhost. The project id was hard-coded to `jobscan-local-dev`. | Emulator is used only off Cloud Run (or with `PUBSUB_USE_EMULATOR=1`); project from `PUBSUB_PROJECT_ID` / `GOOGLE_CLOUD_PROJECT`. |
| 3 | **Jobs silently lost when the DB write failed.** `process_scraped_site` caught every exception and returned normally, so the worker acked and the run was gone. Its own docstring promised the opposite. | Rolls back and raises; the worker nacks and Pub/Sub retries. |
| 4 | **Poison messages looped forever.** Bad JSON and unknown scrapers were nacked; with no dead-letter topic Pub/Sub redelivers them forever. | Logged and acked (a retry can't fix them). Transient errors are still nacked. |
| 5 | **Several messages at once on SQLite.** The Pub/Sub client runs callbacks on 10 threads, not one after another as the docstring said; concurrent writes to SQLite fail with "database is locked" (and were then swallowed, see 3). | `WORKER_CONCURRENCY` (default 4) via flow control, SQLite WAL mode and a 30 s lock wait. |
| 6 | **Companies kept only one job.** Jobs were keyed by URL, and Comeet's `url_active_page` is the company's generic careers page for some companies, e.g. OurCrowd (`https://www.ourcrowd.com/careers` in your DB). All of their positions collapsed into one row. | Jobs are keyed by `(site_id, job_hash)`, the ATS's own id; URL is no longer unique. Comeet uses the per-position hosted page. |
| 7 | **Lever requirements were dropped.** Only `descriptionPlain` was read; Lever puts requirements in `lists` (its README: "extra lists (such as requirements, benefits, etc.)"). The matcher would have seen no must-haves for any Lever job. | Description = `descriptionPlain` + every list + `additionalPlain`, one item per line. |
| 8 | **Greenhouse descriptions had raw HTML tags.** Greenhouse sends `content` entity-encoded (`&lt;p&gt;`), so stripping tags left `<p>…</p>` as text. And the list endpoint does return content with `?content=true` (Greenhouse docs), so the 1 + N requests per board weren't needed. | One request per board with `content=true`, unescaped before stripping. Israel check also looks at `offices`, so "Hybrid" jobs with a Tel Aviv office are kept. |
| 9 | **Stale jobs were hard-deleted**, with no guard against a partial scrape. One bad API response deleted a company's jobs; applications pointing at a job would lose it. | Missing jobs get `closed_at` and are reopened if they return. If a scrape returns under half of the open jobs, nothing is closed except jobs not seen for 7 days. |
| 10 | **Edited postings never updated.** Only `last_seen` (and an empty description) was written. | Title, location, description and URL are updated; `content_hash` + `updated_at` show the matcher what to re-score. |
| 11 | **No company names in the DB.** `seed` stored only the scraper type (`comeet`) and dropped the display name. Biocatch and Gloat were listed twice, and with `autoflush=False` the duplicate check can't see rows added earlier in the same run. | `target_sites.company`, duplicates removed and guarded. |
| 12 | **No way to see a broken scraper.** Scrapers return `[]` on errors, so a dead source (Amazon's expired cookies) looked like "no jobs". | `target_sites.last_status / last_count / last_error / last_run_at` per run. |

Smaller: unused `import random` in `comeet.py`; docstrings that pointed at old paths;
`declarative_base` moved to `sqlalchemy.orm`; `reset_db.py` now also deletes the
`jobs.db-wal` / `-shm` files and refuses to run against a server database.

## Not changed (worth knowing)

- **Legacy files that can't run on this branch:** `main.py` imports
  `infrastructure.quque_system`, `scraper.scraper_agent` and `infrastructure.exceptions`,
  none of which exist here (that's the "2 problems" VS Code shows). With
  `scraper_agent.py`, `schemas.py`, `pubsub_mock.py`, `del.py` and the root `init_db.py`
  (imports `db.database`), it's the old Firecrawl path. Safe to delete.
- **Check Point and Amazon return no descriptions**, so the matcher can only use their titles.
- **`main` is seven months behind**, and it's the branch people see from the link on your CV.
  Merge this branch into `main` once you're happy with it.
- Lever hosts some accounts in the EU (`api.eu.lever.co`). A slug that 404s on the US
  host may live there.
- Comeet throttles by IP when it gets many requests in a short time; keep the cloud
  worker's concurrency modest.

## How to apply

1. Copy the files from the zip over your repo (or `git apply fix-cloud-ready.patch`).
2. Rebuild the local DB once (the schema changed; your September data is stale anyway):
   ```bash
   python reset_db.py
   python seed_comeet_discovery.py
   ```
3. Run the tests: `pip install -r requirements-dev.txt` then `python -m pytest tests`.
   The database tests in `tests/test_db_operations.py` were written but **not run**
   during the review (SQLAlchemy couldn't be installed there), so they're the first
   thing to check.
4. Run the worker and producer as before (see README).
