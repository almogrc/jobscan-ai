"""
seed_sites.py — Insert all known tech company job sources into TargetSite.

Place this file at the project root and run:
    python seed_sites.py

Idempotent: existing rows (matched by base_url) are skipped, not duplicated.
Safe to run multiple times.

SITES format: (display_label, name, base_url)
  name     → routes the worker factory to the correct scraper
  base_url → interpreted differently per scraper:
               comeet     → "uid|token"
               greenhouse → board token slug   e.g. "similarweb"
               lever      → company slug       e.g. "cloudinary"
               checkpoint → full search URL
               amazon     → full search URL
"""

import os
import sys

# ---------------------------------------------------------------------------
# Path bootstrap — lets Python resolve `infrastructure.db` from the root
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from infrastructure.db.database import SessionLocal   # noqa: E402
from infrastructure.db.model import TargetSite        # noqa: E402

# ---------------------------------------------------------------------------
# Master site list
# All entries verified via live URL inspection or search results.
# ---------------------------------------------------------------------------
SITES = [

    # =========================================================================
    # COMEET  (base_url = "uid|token")
    # Source: comeet.com/jobs/{company}/{uid}
    # =========================================================================
    ("Monday.com",   "comeet", "41.00B|14B52C52C67790D3E1296BA37C20"),
    ("Fiverr",       "comeet", "60.002|62188018812631018862C4188"),
    # Lusha  — verified: comeet.com/jobs/lusha/73.00B
    # Token: visit comeet.com/jobs/lusha/73.00B, open DevTools → Network →
    # find /careers-api/ request → copy token param, then add here as:
    # ("Lusha", "comeet", "73.00B|YOUR_TOKEN_HERE"),
    # Rapyd  — verified: comeet.com/jobs/rapyd/73.00E
    # ("Rapyd", "comeet", "73.00E|YOUR_TOKEN_HERE"),

    # =========================================================================
    # GREENHOUSE  (base_url = board token slug)
    # Source: job-boards.greenhouse.io/{SLUG}/jobs/{id}
    # API:    boards-api.greenhouse.io/v1/boards/{SLUG}/jobs
    # =========================================================================
    ("Similarweb",                   "greenhouse", "similarweb"),      # verified: job-boards.greenhouse.io/similarweb
    ("AppsFlyer",                    "greenhouse", "appsflyer"),        # verified: job-boards.greenhouse.io/appsflyer
    ("Tipalti",                      "greenhouse", "tipaltisolutions"),  # verified: job-boards.greenhouse.io/embed/job_board?for=tipaltisolutions
    #("SentinelOne",                  "greenhouse", "sentinelone"),      # in your original list
    #("Lemonade",                     "greenhouse", "lemonade"),         # in your original list
    ("Wolt",                         "greenhouse", "woltisrael"),
    ("Yotpo",                        "greenhouse", "yotpo"),
    ("Rhino Federated Computing",    "greenhouse", "rhinofederatedcomputing"),
    ("Taboola",                      "greenhouse", "taboola"),
    ("Axonius",                      "greenhouse", "axonius"),
    ("Pagayais",                     "greenhouse", "pagayais"),
    ("Cloudflare",                   "greenhouse", "cloudflare"),
    ("Orca Security",                "greenhouse", "orcasecurity"),
    ("Riskified",                    "greenhouse", "riskified"),
    ("Figma",                        "greenhouse", "figma"),
    ("Genscript",                    "greenhouse", "genscript"),
    ("speechify",                    "greenhouse", "speechify"),
    ("biorasillc",                   "greenhouse", "biorasillc"),
    ("armissecurity",                "greenhouse", "armissecurity"),
    ("catonetworks",                 "greenhouse", "catonetworks"),
    ("myheritage",                   "greenhouse", "myheritage"),
    ("postman",                      "greenhouse", "postman"),
    ("feverup",                      "greenhouse", "feverup"),
    ("nebius",                       "greenhouse", "nebius"),
    ("bluevineisrael",               "greenhouse", "bluevineisrael"),
    ("bbyointernal19",               "greenhouse", "bbyointernal19"),
    ("beamup",                       "greenhouse", "beamup"),
    ("nift",                         "greenhouse", "nift"),
    ("nice",                         "greenhouse", "nice"),
    ("forter",                       "greenhouse", "forter"),
    ("hillel",                       "greenhouse", "hillel"),
    ("cymulate",                     "greenhouse", "cymulate"),
    ("rubrik",                       "greenhouse", "rubrik"),
    ("okta",                         "greenhouse", "okta"),
    # =========================================================================
    # LEVER  (base_url = company slug)
    # Source: jobs.lever.co/{SLUG}/{job-id}
    # API:    api.lever.co/v0/postings/{SLUG}?mode=json
    # =========================================================================
    ("Cloudinary",        "lever", "cloudinary"),            # verified: jobs.lever.co/cloudinary
    ("Wiz",               "lever", "wizinc"),                   # in your original list
    #("Gong",              "lever", "gong"),                  # in your original list
    #("Snyk",              "lever", "snyk"),                  # in your original list
    ("CYE",               "lever", "CYE"),
    ("Weloglobal",        "lever", "weloglobal"),
    ("Jobgether",         "lever", "jobgether"),
    ("Parallel Wireless", "lever", "parallelwireless"),
    ("D. Fendsolutions" , "lever", "d-fendsolutions"),
    ("Veeva",             "lever", "veeva"),
    ("Oktopost",          "lever", "oktopost"),
    ("Houzz",             "lever", "houzz"),
    ("Palantir",          "lever", "palantir"),
    ("Smarsh",            "lever", "smarsh"),
    ("Zadara",            "lever", "Zadara"),
    ("Lendbuzz",          "lever", "lendbuzz"),
    # =========================================================================
    # CHECKPOINT  (custom scraper, full search URL)
    # Already seeded by seed_initial_sites() — will be skipped if duplicate
    # =========================================================================
    ("checkpoint", "checkpoint",
     "https://careers.checkpoint.com/index.php?q=&module=cpcareers"
     "&a=search&fa%5B%5D=country_ss%3AIsrael&sort="),

    # =========================================================================
    # AMAZON  (custom scraper, full search URL)
    # Already seeded by seed_initial_sites() — will be skipped if duplicate
    # =========================================================================
    ("Amazon", "amazon",
     "https://www.amazon.jobs/content/en/locations/israel/tel-aviv"),

]

# ---------------------------------------------------------------------------
# TODO — ATS not yet confirmed, need DevTools network tab inspection:
# ---------------------------------------------------------------------------
# Wix    — careers page is React SPA; open DevTools on wix.com/jobs and check
#           for comeet.co, greenhouse.io, or lever.co API calls
# Atera  — Image 4 showed Comeet data in page source; need uid|token from
#           network request to careers-api.greenhouse.io or comeet.com
# Lusha  — UID confirmed (73.00B), token needed from network tab
# Rapyd  — UID confirmed (73.00E), token needed from network tab
# ---------------------------------------------------------------------------


def seed() -> None:
    db = SessionLocal()
    try:
        inserted = 0
        skipped  = 0

        for display, name, base_url in SITES:
            exists = (
                db.query(TargetSite)
                .filter(TargetSite.base_url == base_url)
                .first()
            )

            if exists:
                print(f"  [skip]   {display} already in DB (id={exists.id})")
                skipped += 1
                continue

            db.add(TargetSite(name=name, base_url=base_url, is_active=True))
            print(f"  [insert] {display}  →  name='{name}'  base_url='{base_url}'")
            inserted += 1

        db.commit()
        print(f"\n✅ Done. {inserted} inserted, {skipped} skipped.")

    except Exception as e:
        db.rollback()
        print(f"\n❌ ERROR — rolled back: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("[seed_sites] Seeding TargetSite table...")
    seed()