"""Sitemap and sitemap index parsing (XML and gzip)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Pattern, Sequence, Set, Tuple

MAX_DEPTH = 5
MAX_UNCOMPRESSED = 200 * 1024 * 1024


class SitemapError(Exception):
    """Raised when a sitemap cannot be read or parsed."""


@dataclass
class SitemapCollection:
    """URLs gathered from a sitemap tree."""

    urls: List[str] = field(default_factory=list)
    sitemaps: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    truncated: bool = False
    filtered: int = 0  # URLs dropped by --include / --exclude


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def decompress(content: bytes) -> bytes:
    """Gunzip ``content`` if it starts with the gzip magic number."""
    if content[:2] != b"\x1f\x8b":
        return content
    try:
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = inflater.decompress(content, MAX_UNCOMPRESSED)
    except zlib.error as exc:
        raise SitemapError(f"invalid gzip data: {exc}") from exc
    if inflater.unconsumed_tail:
        raise SitemapError("decompressed sitemap is too large")
    return data


def parse_sitemap(content: bytes) -> Tuple[str, List[str]]:
    """Parse one sitemap document.

    Returns ``("urlset", page_urls)`` or ``("index", child_sitemap_urls)``.
    """
    data = decompress(content)
    if b"<!ENTITY" in data:
        raise SitemapError("XML entity declarations are not allowed")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SitemapError(f"invalid XML: {exc}") from exc
    kind = _local(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise SitemapError(f"not a sitemap (root element <{kind}>)")
    locs: List[str] = []
    for entry in root:
        if _local(entry.tag) not in ("url", "sitemap"):
            continue
        for child in entry:
            if _local(child.tag) == "loc" and child.text and child.text.strip():
                locs.append(child.text.strip())
                break
    return ("index" if kind == "sitemapindex" else "urlset"), locs


def compile_patterns(patterns: Iterable[str]) -> List[Pattern[str]]:
    """Compile regular expressions, raising ``ValueError`` that names the bad one."""
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from exc
    return compiled


def url_allowed(
    url: str, include: Sequence[Pattern[str]] = (), exclude: Sequence[Pattern[str]] = ()
) -> bool:
    """A URL passes if it matches any ``include`` (when given) and no ``exclude`` pattern.

    Patterns are searched anywhere in the URL (``re.search``); anchor them for exact matches.
    """
    if include and not any(p.search(url) for p in include):
        return False
    return not any(p.search(url) for p in exclude)


def collect_urls(
    fetch_bytes: Callable[[str], bytes],
    sitemap_url: str,
    max_urls: Optional[int] = None,
    include: Sequence[Pattern[str]] = (),
    exclude: Sequence[Pattern[str]] = (),
) -> SitemapCollection:
    """Walk a sitemap (or index) and return de-duplicated page URLs in order.

    ``include`` / ``exclude`` filter page URLs before ``max_urls`` is applied.
    A failing child sitemap is recorded in ``errors``; a failing root raises
    :class:`SitemapError`.
    """
    out = SitemapCollection()
    seen_urls: Set[str] = set()
    seen_maps: Set[str] = set()

    def walk(url: str, depth: int) -> bool:
        """Return False once ``max_urls`` has been reached."""
        if url in seen_maps:
            return True
        seen_maps.add(url)
        try:
            kind, locs = parse_sitemap(fetch_bytes(url))
        except Exception as exc:
            if depth == 0:
                raise SitemapError(str(exc)) from exc
            out.errors.append(f"{url}: {exc}")
            return True
        out.sitemaps.append(url)
        if kind == "index":
            if depth >= MAX_DEPTH:
                out.errors.append(f"{url}: sitemap index nested deeper than {MAX_DEPTH}")
                return True
            for child in locs:
                if max_urls is not None and len(out.urls) >= max_urls:
                    out.truncated = True
                    return False
                if not walk(child, depth + 1):
                    return False
            return True
        for loc in locs:
            if loc in seen_urls:
                continue
            if not url_allowed(loc, include, exclude):
                seen_urls.add(loc)
                out.filtered += 1
                continue
            if max_urls is not None and len(out.urls) >= max_urls:
                out.truncated = True
                return False
            seen_urls.add(loc)
            out.urls.append(loc)
        return True

    walk(sitemap_url, 0)
    return out
