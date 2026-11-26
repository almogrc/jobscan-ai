"""
worker.py ack/nack contract. The DB and Pub/Sub modules are replaced with fakes,
so these tests need neither SQLAlchemy nor google-cloud-pubsub.
"""

import importlib
import json
import sys
import types

import pytest


class FakeMessage:
    def __init__(self, payload):
        self.data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.acked = self.nacked = False

    def ack(self):
        self.acked = True

    def nack(self):
        self.nacked = True


@pytest.fixture
def worker(monkeypatch):
    db_calls = {"process": [], "record": []}

    fake_db = types.ModuleType("infrastructure.db.db_operations")

    def process_scraped_site(site_id, scraped_jobs, scanned_at_str):
        if db_calls.get("fail_db"):
            raise RuntimeError("database is locked")
        db_calls["process"].append((site_id, list(scraped_jobs)))

    fake_db.process_scraped_site = process_scraped_site
    fake_db.record_site_run = lambda *args, **kwargs: db_calls["record"].append(args)
    fake_db.ensure_schema = lambda: None

    fake_pubsub = types.ModuleType("infrastructure.queue_system.gcp_pubsub")
    fake_pubsub.GCPPubSubClient = object

    monkeypatch.setitem(sys.modules, "infrastructure.db.db_operations", fake_db)
    monkeypatch.setitem(sys.modules, "infrastructure.queue_system.gcp_pubsub", fake_pubsub)
    monkeypatch.delitem(sys.modules, "worker", raising=False)
    module = importlib.import_module("worker")
    module.db_calls = db_calls
    yield module
    sys.modules.pop("worker", None)


def _async_returning(value):
    async def scraper(url):
        if isinstance(value, Exception):
            raise value
        return value
    return scraper


SITE = {"id": 7, "name": "comeet", "url": "D3.00A|TOKEN", "company": "OurCrowd"}


def test_success_is_saved_then_acked(worker, monkeypatch):
    monkeypatch.setattr(worker, "scrape_comeet", _async_returning([{"title": "QA", "url": "u", "job_hash": "1"}]))
    message = FakeMessage(SITE)
    worker.process_message(message)
    assert message.acked and not message.nacked
    assert worker.db_calls["process"] == [(7, [{"title": "QA", "url": "u", "job_hash": "1"}])]


def test_empty_run_is_still_recorded(worker, monkeypatch):
    monkeypatch.setattr(worker, "scrape_comeet", _async_returning([]))
    message = FakeMessage(SITE)
    worker.process_message(message)
    assert message.acked
    assert worker.db_calls["process"] == [(7, [])]


def test_db_failure_is_nacked_not_swallowed(worker, monkeypatch):
    monkeypatch.setattr(worker, "scrape_comeet", _async_returning([{"title": "QA", "url": "u"}]))
    worker.db_calls["fail_db"] = True
    message = FakeMessage(SITE)
    worker.process_message(message)
    assert message.nacked and not message.acked


def test_scraper_exception_is_nacked_and_recorded(worker, monkeypatch):
    monkeypatch.setattr(worker, "scrape_comeet", _async_returning(TimeoutError("comeet timed out")))
    message = FakeMessage(SITE)
    worker.process_message(message)
    assert message.nacked
    assert worker.db_calls["record"][0][:2] == (7, "error")


def test_unknown_scraper_is_dropped_instead_of_looping(worker):
    message = FakeMessage(dict(SITE, name="workday"))
    worker.process_message(message)
    assert message.acked and not message.nacked
    assert worker.db_calls["process"] == []


@pytest.mark.parametrize("payload", [b"not json", b"[1, 2]", json.dumps({"name": "comeet"}).encode()])
def test_undecodable_message_is_dropped_instead_of_looping(worker, payload):
    message = FakeMessage(payload)
    worker.process_message(message)
    assert message.acked and not message.nacked
