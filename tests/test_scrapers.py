"""Scraper tests. Every HTTP call goes to tests/fakes.FakeSession, never to the network."""

import asyncio

import aiohttp

from fakes import FakeSession
from scrapers import amazon, comeet, greenhouse, lever
from scrapers.common import html_to_text, is_israel_location


def run(coro):
    return asyncio.run(coro)


# --- Comeet -----------------------------------------------------------------

def _comeet_position(uid, name, country="IL", active="https://www.ourcrowd.com/careers"):
    return {
        "uid": uid,
        "name": name,
        "location": {"name": "Jerusalem", "country": country},
        "url_active_page": active,
        "url_comeet_hosted_page": f"https://www.comeet.com/jobs/ourcrowd/D3.00A/x/{uid}",
        "details": [
            {"name": "Description", "value": "<p>Join us</p>"},
            {"name": "Requirements", "value": "<ul><li>3+ years Python</li><li>SQL</li></ul>"},
        ],
    }


def test_comeet_keeps_every_position_when_they_share_one_careers_page(monkeypatch):
    payload = [_comeet_position("9E.171", "VP Finance"),
               _comeet_position("9E.172", "Investment Analyst"),
               _comeet_position("9E.173", "Backend Developer"),
               _comeet_position("9E.174", "NYC Sales", country="US")]
    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession.serving({"careers-api/2.0/company/D3.00A": payload}))

    jobs = run(comeet.scrape_comeet("D3.00A|TOKEN"))

    assert [j["title"] for j in jobs] == ["VP Finance", "Investment Analyst", "Backend Developer"]
    assert len({j["url"] for j in jobs}) == 3
    assert jobs[0]["description"].splitlines() == ["Description", "Join us", "Requirements", "3+ years Python", "SQL"]


def test_comeet_prefers_the_renamed_recruit_hosted_field():
    job = _comeet_position("1", "QA")
    job["url_recruit_hosted_page"] = "https://www.comeet.com/jobs/new-name/1"
    mapped = comeet._map_job(job)
    assert mapped is not None and mapped["url"] == "https://www.comeet.com/jobs/new-name/1"


# --- Lever ------------------------------------------------------------------

LEVER_POSTING = {
    "id": "abc",
    "text": "Backend Engineer",
    "hostedUrl": "https://jobs.lever.co/acme/abc",
    "country": "IL",
    "categories": {"location": "Tel Aviv"},
    "descriptionPlain": "We build payments infrastructure.",
    "lists": [
        {"text": "Requirements", "content": "<li>3+ years of Python</li><li>PostgreSQL</li>"},
        {"text": "Advantages", "content": "<li>Kubernetes</li>"},
    ],
    "additionalPlain": "Hybrid, 3 days a week.",
}


def test_lever_description_includes_the_requirement_lists():
    text = lever._extract_description(LEVER_POSTING)
    assert text.splitlines() == [
        "We build payments infrastructure.",
        "Requirements", "3+ years of Python", "PostgreSQL",
        "Advantages", "Kubernetes",
        "Hybrid, 3 days a week.",
    ]


def test_lever_filters_to_israel(monkeypatch):
    abroad = dict(LEVER_POSTING, id="x", country="US", categories={"location": "New York"})
    keyword_only = dict(LEVER_POSTING, id="y", country=None, categories={"location": "Herzliya"})
    monkeypatch.setattr(aiohttp, "ClientSession",
                        FakeSession.serving({"api.lever.co/v0/postings/acme": [LEVER_POSTING, abroad, keyword_only]}))
    jobs = run(lever.scrape_lever("acme"))
    assert [j["job_hash"] for j in jobs] == ["abc", "y"]


# --- Greenhouse -------------------------------------------------------------

def test_greenhouse_one_request_decoded_content_and_office_check(monkeypatch):
    payload = {"jobs": [
        {"id": 1, "title": "Data Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
         "location": {"name": "Tel Aviv, Israel"},
         # Greenhouse sends the description HTML-entity-encoded (their docs say so)
         "content": "&lt;p&gt;&lt;strong&gt;Requirements&lt;/strong&gt;&lt;/p&gt;"
                    "&lt;ul&gt;&lt;li&gt;3+ years Node.js&lt;/li&gt;&lt;li&gt;R&amp;amp;D mindset&lt;/li&gt;&lt;/ul&gt;"},
        {"id": 2, "title": "Hybrid SRE", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
         "location": {"name": "Hybrid"}, "offices": [{"name": "Tel Aviv"}], "content": ""},
        {"id": 3, "title": "Account Executive", "absolute_url": "https://boards.greenhouse.io/acme/jobs/3",
         "location": {"name": "London"}, "offices": [{"name": "London"}], "content": ""},
    ]}
    factory = FakeSession.serving({"boards-api.greenhouse.io/v1/boards/acme/jobs": payload})
    monkeypatch.setattr(aiohttp, "ClientSession", factory)

    jobs = run(greenhouse.scrape_greenhouse("acme"))

    assert [j["job_hash"] for j in jobs] == ["1", "2"]
    assert jobs[0]["description"].splitlines() == ["Requirements", "3+ years Node.js", "R&D mindset"]
    assert "<" not in jobs[0]["description"]
    assert len(factory.calls) == 1 and "content=true" in factory.calls[0]


# --- Amazon -----------------------------------------------------------------

def test_amazon_without_credentials_skips_without_a_request(monkeypatch):
    monkeypatch.setattr(amazon, "SESSION_COOKIES", "")
    monkeypatch.setattr(amazon, "API_KEY", "")
    factory = FakeSession.serving({})
    monkeypatch.setattr(aiohttp, "ClientSession", factory)
    assert run(amazon.scrape_amazon("ignored")) == []
    assert factory.calls == []


# --- common -----------------------------------------------------------------

def test_israel_keywords():
    for place in ("Yokneam, Israel", "Airport City", "Petah-Tikva", "Herzliya Pituach", "Tel Aviv-Yafo"):
        assert is_israel_location(place), place
    for place in ("London", "Lodz, Poland", "New York", "Remote"):
        assert not is_israel_location(place), place


def test_html_to_text_handles_plain_and_encoded_html():
    assert html_to_text("<p>a</p><p>b</p>") == "a\nb"
    assert html_to_text("&lt;p&gt;a&lt;/p&gt;&lt;p&gt;b&lt;/p&gt;") == "a\nb"
    assert html_to_text("") == ""
