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
from infrastructure.db.database import engine
from infrastructure.db.model import Base
Base.metadata.create_all(bind=engine)
# ---------------------------------------------------------------------------
# Master site list
# All entries verified via live URL inspection or search results.
# ---------------------------------------------------------------------------
SITES = [

    # =========================================================================
    # COMEET  (base_url = "uid|token")
    # Source: comeet.com/jobs/{company}/{uid}
    # =========================================================================
    ("Monday.com",        "comeet", "41.00B|14B52C52C67790D3E1296BA37C20"),
    ("Fiverr",            "comeet", "60.002|62188018812631018862C4188"),
    ("Flexor",            "comeet", "F9.006|9F645BA1DE213EC31CE1DE2059A613EC3BC4"), # מצאת! 
    ("Tastewise",         "comeet", "F8.000|8F035A047802CB047803E90478035A001AD0"), 
    ("OurCrowd",          "comeet", "D3.00A|3DA1342F683DA22AAF683DAF68F68F68"),
    ("AudioCodes",        "comeet", "85.004|5841B942C2058431A4108C269C108C0108C"),
    ("Pi-Cardia",         "comeet", "A5.00B|5AB1C573303B5633032D581C571C5716ACB56"),
    ("Maytronics",        "comeet", "E3.008|3E81388FA0BB83E8FA0BB813881F401B58"),
    ("Quantum Machines",  "comeet", "D6.000|6D028E0DA022106D01470221036803D502210"),
    ("ThetaRay",          "comeet", "72.00F|27F9FC16779FC13F8EFA13F84FE27F77D"),
    ("Dust Photonics",    "comeet", "05.00B|50B1937234D0234D0F211E422D6350B"),
    ("Anecdotes",         "comeet", "F9.00B|9FB45DD1DF11DF113F69FB59D345DD13F61DF1"),
    ("Cross River",       "comeet", "C7.00F|7CF2EDA1F3C270B1F3CF9E4647270B4647270B"),
    ("Xtend",             "comeet", "85.00A|58A1BB22C50B14213C162858A213C26C61628"),
    ("BuyMe",             "comeet", "B2.008|2B8D980AE01050570D98187815C0570"),
    ("44ventures",        "comeet", "18.001|8113066285581118334088408803877811"),
    ("JDC",               "comeet", "F3.004|3F413C4FD0FD0BDC17B807E87E8BDC"),
    ("Abra RND",             "comeet", "15.007|517197323A1A2E1973A2E145CA2E0A2E"),
    ("Cyera",             "comeet", "17.008|7182A90154871823783FD838C031A802378"),
    ("Buildots",             "comeet", "36.004|6342538634037D42B6C129C18D0129CC68"),
    ("Uppro",             "comeet", "18.003|8133072285F102604098183918393885285F"),
    ("Genpact",             "comeet", "B9.008|9B8440813709B84DC01D283A501D2826E026E0"),
    ("Novidea",             "comeet", "E5.00A|5EA237C0BD41D920353A17A8353A0"),
    ("Navina",             "comeet", "E6.00C|6EC2988DD837606EC376014C43E4C376014C4"),
    ("Percepto",             "comeet", "44.000|440154015404400088019802640880"),
    ("Dealhub",             "comeet", "86.005|685271E6853AAD1A14D0A2099138F2DA33428"),
    ("Guardio",             "comeet", "57.000|7502BE015F0249041D01D40EA03A801D40EA0"),
    ("Maelys Cosmetics",     "comeet", "68.002|862324C324C324C29EA192604B72218829EA"),
    ("Paragon",             "comeet", "76.006|67626C46762D3A33B02D3A204E26C4676676"),
    ("Arpeely",             "comeet", "57.001|7512BE615F3249541D91D4415F31D4441D9EA2"),
    ("Cynet",             "comeet", "33.00D|33D103133D19E8136E1D25103133D10311D25"),
    ("Claroty",             "comeet", "F2.004|2F4EC42F42F45E814AC1A945E814AC5E8"),
    ("Cardosystems",             "comeet", "F2.003|2F3EBF2F32F35E614A58D9BCC11B2EBF"),
    ("Mdclone",             "comeet", "66.004|6642658664265826580CC800CC8"),
    ("Liveu",             "comeet", "90.00C|9C2709C1D43A827030C3A82709C"),
    ("Biocatch",             "comeet", "03.00E|30EF4630E92A1562156292A92A61C92A"),
    ("Playstudios",             "comeet", "E2.00B|2EBE972EB0146D8C1E971182E975D6"),
    ("Biocatch",             "comeet", "03.00E|30EF4630E92A1562156292A92A61C92A"),
    ("Solaredge",             "comeet", "71.00A|17A5E8762BD08DC46E46E46E046E"),
    ("Appsforce",             "comeet", "09.00C|90C3648516C90C2430516C3F541218516C1218"),
    ("Rapyd",                "comeet", "73.00E|37E11766FC1F6E11761F6E6FC01BF06FC"),
    ("Ilyon",                "comeet", "42.00A|24A9281250DBCDBC928DBC494149A928"),
    ("CyCognito",                "comeet", "14.00A|41A148210681CB61CB68341CB624EAC4E1482"),
    ("Chargeflow",                "comeet", "29.001|92136C652292DA51B6301B631B6303FE7"),
    ("Moonshot",                "comeet", "87.005|7852D1E168F43AD2D1E2D1E168F1E1434A32599"),
    ("Rewire",                "comeet", "34.00D|43D153115310196E1DAB43D021E81DAB"),
    ("Infinidat",                "comeet", "D6.003|6D328F2DA6221F221F221F221F002FC5"),
    ("Gloat",                "comeet", "E5.000|5E02340002F0017800234011A01780"),
    ("Silverfort",                "comeet", "54.007|45715B315B38AE22B8D051A0A457D051E61"),
    ("Gloat",                "comeet", "E5.000|5E02340002F0017800234011A01780"),
    ("Mitiga",                "comeet", "26.00B|62B250262B012811ED718AC128112813158"),
    ("Recruitingteam",                "comeet", "F3.00B|3FB13E7FEC13E70BF1BF13FB13E7BF1"),
    # Lusha  — verified: comeet.com/jobs/lusha/73.00B
    # Token: visit comeet.com/jobs/lusha/73.00B, open DevTools → Network →
    # find /careers-api/ request → copy token param, then add here as:
    # ("Lusha", "comeet", "73.00B|YOUR_TOKEN_HERE"),
  

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
    ("Canonical",                    "greenhouse", "canonical"), 
    ("WeDev",                        "greenhouse", "wedev"), 
    ("Torq",                         "greenhouse", "torq"), 
    ("Honeycomb Insurance",          "greenhouse", "honeycombinsurance"),
    ("Pontera",                         "greenhouse", "pontera"), 
    ("Gongio",                         "greenhouse", "gongio"), 
    
    

    
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
    ("Mobileye",          "lever", "mobileye"),
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