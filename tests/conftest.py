"""
Test setup.

* Puts the repo root and services/discovery-agent on sys.path, the same way
  worker.py and producer.py bootstrap themselves.
* Points DATABASE_URL at a throwaway SQLite file BEFORE anything imports
  infrastructure.db, so tests never touch your real jobs.db.
* If aiohttp isn't installed, registers a tiny stand-in so the scraper modules
  can be imported. Scraper tests replace ClientSession with a fake anyway, so
  no test ever makes a network call.
"""

import os
import sys
import tempfile
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AGENT = os.path.join(ROOT, "services", "discovery-agent")
for path in (ROOT, AGENT):
    if path not in sys.path:
        sys.path.insert(0, path)

_TMP_DIR = tempfile.mkdtemp(prefix="jobscan-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ.setdefault("PUBSUB_USE_EMULATOR", "1")

try:
    import aiohttp  # noqa: F401
except ImportError:  # pragma: no cover - only in environments without aiohttp
    stub = types.ModuleType("aiohttp")

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class ClientResponseError(Exception):
        def __init__(self, *args, status=0, message="", **kwargs):
            super().__init__(message)
            self.status = status
            self.message = message

    class ClientConnectionError(Exception):
        pass

    class ContentTypeError(Exception):
        pass

    class CookieJar:
        def __init__(self, *args, **kwargs):
            pass

    class ClientSession:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("tests must replace aiohttp.ClientSession with a fake")

    for _cls in (ClientTimeout, ClientResponseError, ClientConnectionError,
                 ContentTypeError, CookieJar, ClientSession):
        setattr(stub, _cls.__name__, _cls)
    sys.modules["aiohttp"] = stub
