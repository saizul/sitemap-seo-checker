"""Sitemap and sitemap index parsing (XML and gzip)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, List, Optional, Pattern, Sequence, Set, Tuple

from .sitemap_lint import SitemapEntry, SitemapFinding, lint_document, merge_findings

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
    findings: List[SitemapFinding] = field(default_factory=list)  # protocol checks per file


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


def parse_entries(content: bytes) -> Tuple[str, List[SitemapEntry], int]:
    """Parse one sitemap document into its entries.

    Returns ``(kind, entries, uncompressed_size)`` where ``kind`` is ``"urlset"`` or
    ``"index"`` and each entry carries ``loc`` and the raw ``lastmod`` text.
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
    entries: List[SitemapEntry] = []
    for entry in root:
        if _local(entry.tag) not in ("url", "sitemap"):
            continue
        loc = lastmod = ""
        for child in entry:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "loc" and text and not loc:
                loc = text
            elif name == "lastmod" and text and not lastmod:
                lastmod = text
        if loc:
            entries.append(SitemapEntry(loc, lastmod))
    return ("index" if kind == "sitemapindex" else "urlset"), entries, len(data)


def parse_sitemap(content: bytes) -> Tuple[str, List[str]]:
    """Parse one sitemap document.

    Returns ``("urlset", page_urls)`` or ``("index", child_sitemap_urls)``.
    """
    kind, entries, _ = parse_entries(content)
    return kind, [e.loc for e in entries]


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
    now: Optional[datetime] = None,
) -> SitemapCollection:
    """Walk a sitemap (or index) and return de-duplicated page URLs in order.

    ``include`` / ``exclude`` filter page URLs before ``max_urls`` is applied.
    A failing child sitemap is recorded in ``errors``; a failing root raises
    :class:`SitemapError`. Every file that was read is also checked against the sitemap
    protocol; the results are in ``findings`` (``now`` is used for future ``lastmod`` checks).
    """
    out = SitemapCollection()
    seen_urls: Set[str] = set()
    seen_maps: Set[str] = set()
    duplicates: List[SitemapFinding] = []

    def walk(url: str, depth: int, parent_is_index: bool = False) -> bool:
        """Return False once ``max_urls`` has been reached."""
        if url in seen_maps:
            return True
        seen_maps.add(url)
        try:
            kind, entries, size = parse_entries(fetch_bytes(url))
        except Exception as exc:
            if depth == 0:
                raise SitemapError(str(exc)) from exc
            out.errors.append(f"{url}: {exc}")
            return True
        out.sitemaps.append(url)
        out.findings.extend(lint_document(url, kind, entries, size, now))
        locs = [e.loc for e in entries]
        if kind == "index" and parent_is_index:
            out.findings.append(SitemapFinding(url, "nested-index"))
        if kind == "index":
            if depth >= MAX_DEPTH:
                out.errors.append(f"{url}: sitemap index nested deeper than {MAX_DEPTH}")
                return True
            for child in locs:
                if max_urls is not None and len(out.urls) >= max_urls:
                    out.truncated = True
                    return False
                if not walk(child, depth + 1, True):
                    return False
            return True
        for loc in locs:
            if loc in seen_urls:
                duplicates.append(SitemapFinding(url, "duplicate-loc", 1, [loc]))
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
    out.findings.extend(merge_findings(duplicates))
    return out
