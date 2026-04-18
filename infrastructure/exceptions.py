class PermanentScrapingError(Exception):
    """Raised when a permanent error occurs (e.g., 404 Not Found, invalid DOM)."""
    def __init__(self, message, url, status_code=None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class TransientNetworkError(Exception):
    """Raised when a temporary network issue occurs (e.g., Timeout, 500, 502)."""
    def __init__(self, message, url, status_code=None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class RateLimitError(Exception):
    """Raised when blocked by the target site (e.g., 429 Too Many Requests, 403 Forbidden)."""
    def __init__(self, message, url, status_code=None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code