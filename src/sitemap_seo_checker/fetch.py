"""HTTP fetching with retries, a per-request delay and thread-local sessions."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

DEFAULT_USER_AGENT = "sitemap-seo-checker"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_SITEMAP_BYTES = 50 * 1024 * 1024


class FetchError(Exception):
    """Raised by :meth:`Fetcher.get_bytes` when a download fails."""


@dataclass
class FetchResult:
    """Outcome of one fetch. ``response`` is None when the request failed."""

    response: Optional[requests.Response]
    error: str = ""
    elapsed_ms: float = 0.0


class Fetcher:
    """Shared by all worker threads; each thread gets its own session."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 15.0,
        delay: float = 0.0,
        retries: int = 1,
        backoff: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.delay = delay
        self.retries = max(0, retries)
        self.backoff = backoff
        self._sleep = sleep
        self._local = threading.local()

    def session(self) -> requests.Session:
        """The calling thread's session."""
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers["User-Agent"] = self.user_agent
            self._local.session = sess
        return sess

    def fetch(self, url: str, stream: bool = True) -> FetchResult:
        """GET ``url`` following redirects; retries 429/5xx and network errors."""
        error = ""
        for attempt in range(self.retries + 1):
            if self.delay > 0:
                self._sleep(self.delay)
            started = time.perf_counter()
            try:
                resp = self.session().get(url, timeout=self.timeout, stream=stream)
            except requests.RequestException as exc:
                error = f"{exc.__class__.__name__}: {exc}"[:200]
                if attempt < self.retries:
                    self._sleep(self.backoff * 2**attempt)
                    continue
                return FetchResult(None, error)
            elapsed = (time.perf_counter() - started) * 1000
            if resp.status_code in RETRY_STATUSES and attempt < self.retries:
                resp.close()
                self._sleep(self.backoff * 2**attempt)
                continue
            return FetchResult(resp, "", elapsed)
        return FetchResult(None, error)

    def get_bytes(self, url: str, max_bytes: int = MAX_SITEMAP_BYTES) -> bytes:
        """Download a body (used for sitemaps); raises :class:`FetchError`."""
        result = self.fetch(url)
        if result.response is None:
            raise FetchError(f"{url}: {result.error}")
        resp = result.response
        try:
            if resp.status_code != 200:
                raise FetchError(f"{url}: HTTP {resp.status_code}")
            data = bytearray()
            for chunk in resp.iter_content(65536):
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise FetchError(f"{url}: larger than {max_bytes} bytes")
            return bytes(data)
        finally:
            resp.close()
