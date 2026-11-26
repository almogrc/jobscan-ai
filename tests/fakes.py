"""A fake aiohttp.ClientSession that serves canned JSON by URL substring."""


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            import aiohttp
            raise aiohttp.ClientResponseError(status=self.status, message="fake error")

    async def json(self, content_type=None):
        return self._payload


class FakeSession:
    """Use: monkeypatch.setattr(aiohttp, "ClientSession", FakeSession.serving({...}))"""

    def __init__(self, routes, calls):
        self._routes = routes
        self.calls = calls

    @classmethod
    def serving(cls, routes):
        calls = []

        def factory(*args, **kwargs):
            return cls(routes, calls)

        factory.calls = calls
        return factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        self.calls.append(url)
        for fragment, payload in self._routes.items():
            if fragment in url:
                return FakeResponse(payload)
        return FakeResponse({}, status=404)
