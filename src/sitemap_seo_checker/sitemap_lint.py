"""Sitemap protocol checks: limits, <loc> and <lastmod> values, host and path scope.

These look at the sitemap files themselves rather than the pages they list. The rules follow
https://www.sitemaps.org/protocol.html and Google's sitemap guidelines.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .models import ERROR, NOTICE, WARNING

MAX_ENTRIES = 50_000
MAX_BYTES = 50 * 1024 * 1024  # 52,428,800 bytes, uncompressed
MAX_LOC_LENGTH = 2048
MAX_EXAMPLES = 5
#: lastmod values this far ahead of the current time are reported (allows for clock skew)
FUTURE_TOLERANCE = timedelta(days=1)

#: finding code -> (level, description)
SITEMAP_ISSUES: Dict[str, Tuple[str, str]] = {
    "too-many-entries": (ERROR, f"More than {MAX_ENTRIES:,} entries in one sitemap file"),
    "too-large": (ERROR, "Larger than 50 MB (52,428,800 bytes) uncompressed"),
    "invalid-loc": (ERROR, "<loc> is not an absolute http(s) URL"),
    "loc-too-long": (WARNING, f"<loc> is {MAX_LOC_LENGTH} characters or longer"),
    "invalid-lastmod": (WARNING, "<lastmod> is not a W3C datetime (e.g. 2026-01-31)"),
    "future-lastmod": (WARNING, "<lastmod> is in the future"),
    "off-host": (WARNING, "URL is on another host than the sitemap (needs cross-site proof)"),
    "nested-index": (WARNING, "Sitemap index lists another sitemap index"),
    "duplicate-loc": (NOTICE, "URL already listed earlier in the sitemap tree"),
    "out-of-scope": (NOTICE, "URL is outside the sitemap's directory"),
    "empty-sitemap": (NOTICE, "Sitemap file lists no URLs"),
}  # fmt: skip

_W3C = re.compile(
    r"^(?P<y>\d{4})(?:-(?P<m>\d{2})(?:-(?P<d>\d{2})"
    r"(?:T(?P<H>\d{2}):(?P<M>\d{2})(?::(?P<S>\d{2})(?:\.\d+)?)?(?P<tz>Z|[+-]\d{2}:\d{2}))?)?)?$"
)


@dataclass
class SitemapEntry:
    """One <url> or <sitemap> element."""

    loc: str
    lastmod: str = ""


@dataclass
class SitemapFinding:
    """A problem found in one sitemap file. Per-URL problems are grouped by code."""

    sitemap: str
    code: str
    count: int = 1
    examples: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def level(self) -> str:
        return sitemap_issue_level(self.code)

    @property
    def description(self) -> str:
        return SITEMAP_ISSUES.get(self.code, (NOTICE, ""))[1]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["level"] = self.level
        return data


def sitemap_issue_level(code: str) -> str:
    """Level (error/warning/notice) of a sitemap finding code."""
    return SITEMAP_ISSUES.get(code, (NOTICE, ""))[0]


def parse_w3c_datetime(value: str) -> Optional[datetime]:
    """Parse a W3C datetime (the ISO 8601 profile used by <lastmod>) into an aware UTC datetime.

    Accepts ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD`` and date-times with a required time zone
    designator (``Z`` or ``+hh:mm``). Returns None for anything else, including impossible dates.
    """
    match = _W3C.match(value.strip())
    if not match:
        return None
    g = match.groupdict()
    try:
        moment = datetime(
            int(g["y"]), int(g["m"] or 1), int(g["d"] or 1),
            int(g["H"] or 0), int(g["M"] or 0), int(g["S"] or 0), tzinfo=timezone.utc,
        )  # fmt: skip
    except ValueError:
        return None
    tz = g["tz"]
    if tz and tz != "Z":
        hours, minutes = int(tz[1:3]), int(tz[4:6])
        if hours > 23 or minutes > 59:
            return None
        offset = timedelta(hours=hours, minutes=minutes)
        moment = moment - offset if tz[0] == "+" else moment + offset
    return moment


def is_absolute_http(url: str) -> bool:
    """True for ``http://`` / ``https://`` URLs with a host and no whitespace."""
    if not url or any(ch.isspace() for ch in url):
        return False
    parts = urlparse(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _scope(sitemap_url: str) -> Tuple[str, str]:
    """(host, directory path) a sitemap may list URLs for."""
    parts = urlparse(sitemap_url)
    directory = parts.path.rsplit("/", 1)[0] + "/"
    return (parts.hostname or "").lower(), directory


class _Grouper:
    """Collects per-URL findings as one finding per code with a few examples."""

    def __init__(self, sitemap: str) -> None:
        self.sitemap = sitemap
        self.found: Dict[str, SitemapFinding] = {}

    def add(self, code: str, example: str) -> None:
        item = self.found.get(code)
        if item is None:
            self.found[code] = SitemapFinding(self.sitemap, code, 1, [example])
            return
        item.count += 1
        if len(item.examples) < MAX_EXAMPLES:
            item.examples.append(example)

    def findings(self) -> List[SitemapFinding]:
        return list(self.found.values())


def lint_document(
    sitemap_url: str,
    kind: str,
    entries: Iterable[SitemapEntry],
    size: int,
    now: Optional[datetime] = None,
) -> List[SitemapFinding]:
    """Check one parsed sitemap file.

    ``kind`` is ``"urlset"`` or ``"index"``; ``size`` is the uncompressed size in bytes.
    Host and directory scope only apply when the sitemap URL itself is absolute.
    """
    now = now or datetime.now(timezone.utc)
    entries = list(entries)
    out: List[SitemapFinding] = []
    if len(entries) > MAX_ENTRIES:
        out.append(
            SitemapFinding(sitemap_url, "too-many-entries", detail=f"{len(entries):,} entries")
        )
    if size > MAX_BYTES:
        out.append(SitemapFinding(sitemap_url, "too-large", detail=f"{size:,} bytes"))
    if kind == "urlset" and not entries:
        out.append(SitemapFinding(sitemap_url, "empty-sitemap"))

    group = _Grouper(sitemap_url)
    scoped = is_absolute_http(sitemap_url)
    host, directory = _scope(sitemap_url) if scoped else ("", "")
    for entry in entries:
        loc = entry.loc
        if not is_absolute_http(loc):
            group.add("invalid-loc", loc)
        else:
            if len(loc) >= MAX_LOC_LENGTH:
                group.add("loc-too-long", loc[:120] + "...")
            parts = urlparse(loc)
            if scoped and (parts.hostname or "").lower() != host:
                group.add("off-host", loc)
            elif scoped and kind == "urlset" and not (parts.path or "/").startswith(directory):
                group.add("out-of-scope", loc)
        if entry.lastmod:
            moment = parse_w3c_datetime(entry.lastmod)
            if moment is None:
                group.add("invalid-lastmod", f"{loc} ({entry.lastmod})")
            elif moment > now + FUTURE_TOLERANCE:
                group.add("future-lastmod", f"{loc} ({entry.lastmod})")
    return out + group.findings()


def merge_findings(findings: Iterable[SitemapFinding]) -> List[SitemapFinding]:
    """Combine findings with the same sitemap and code (used for duplicate-loc)."""
    merged: Dict[Tuple[str, str], SitemapFinding] = {}
    for item in findings:
        key = (item.sitemap, item.code)
        if key not in merged:
            merged[key] = SitemapFinding(item.sitemap, item.code, 0, [], item.detail)
        target = merged[key]
        target.count += item.count
        for example in item.examples:
            if len(target.examples) < MAX_EXAMPLES:
                target.examples.append(example)
    return list(merged.values())


def sort_findings(findings: Iterable[SitemapFinding]) -> List[SitemapFinding]:
    """Errors first, then warnings, then notices; stable within a level."""
    rank = {ERROR: 0, WARNING: 1, NOTICE: 2}
    return sorted(findings, key=lambda f: rank.get(f.level, 3))
