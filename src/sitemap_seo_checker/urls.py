"""URL helpers used for comparing and grouping URLs."""

from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlparse

_STATIC_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js", ".json",
    ".xml", ".pdf", ".zip", ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".txt",
)  # fmt: skip


def host_key(url: str) -> str:
    """Lower-case host without ``www.`` and default ports."""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def url_key(url: str) -> str:
    """Comparison key: host, path without trailing slash, and query (scheme ignored)."""
    parts = urlparse(url.strip())
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{host_key(url)}{path}{query}"


def absolutize(base: str, href: str) -> str:
    """Resolve ``href`` against ``base`` and drop the fragment."""
    return urldefrag(urljoin(base, href.strip()))[0]


def is_page_like(url: str) -> bool:
    """False for obvious static assets (images, scripts, documents)."""
    return not urlparse(url).path.lower().endswith(_STATIC_EXTENSIONS)
