"""Data models and the issue catalogue."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

ERROR = "error"
WARNING = "warning"
NOTICE = "notice"

#: issue code -> (level, description)
ISSUES: Dict[str, Tuple[str, str]] = {
    "fetch-error": (ERROR, "URL could not be fetched"),
    "non-200": (ERROR, "Final status is not 200"),
    "noindex": (ERROR, "noindex in meta robots or X-Robots-Tag"),
    "blocked-by-robots": (ERROR, "URL is disallowed by robots.txt"),
    "canonical-other": (ERROR, "Canonical points to a different URL"),
    "redirect": (WARNING, "URL redirects"),
    "duplicate-title": (WARNING, "Title shared with another sitemap URL"),
    "missing-title": (WARNING, "No <title>"),
    "missing-h1": (WARNING, "No <h1>"),
    "orphan": (WARNING, "No internal links from other sitemap pages"),
    "hreflang-no-return": (WARNING, "hreflang target does not link back"),
    "hreflang-missing-self": (WARNING, "hreflang set has no self-reference"),
    "hreflang-invalid-code": (WARNING, "Invalid hreflang language code"),
    "hreflang-conflict": (WARNING, "Same hreflang code points to different URLs"),
    "canonical-missing": (NOTICE, "No canonical link"),
    "multiple-h1": (NOTICE, "More than one <h1>"),
    "title-too-long": (NOTICE, "Title longer than 60 characters"),
    "missing-description": (NOTICE, "No meta description"),
    "description-too-long": (NOTICE, "Meta description longer than 160 characters"),
}

#: issue codes computed across pages (recomputed on every run, never cached)
CROSS_PAGE = {
    "blocked-by-robots", "duplicate-title", "orphan", "hreflang-no-return",
    "hreflang-missing-self", "hreflang-invalid-code", "hreflang-conflict",
}  # fmt: skip


def issue_level(code: str) -> str:
    """Level (error/warning/notice) of an issue code."""
    return ISSUES.get(code, (NOTICE, ""))[0]


@dataclass
class PageResult:
    """Everything learned about one sitemap URL."""

    url: str
    status: Optional[int] = None  # status of the first response
    final_status: Optional[int] = None  # status after redirects
    redirects: int = 0
    final_url: str = ""
    canonical: str = ""
    canonical_state: str = "n/a"  # self | other | missing | n/a
    meta_robots: str = ""
    x_robots_tag: str = ""
    noindex: bool = False
    title: str = ""
    title_length: int = 0
    meta_description_length: int = 0
    h1_count: int = 0
    response_time_ms: Optional[int] = None
    content_type: str = ""
    is_html: bool = False
    hreflang: List[List[str]] = field(default_factory=list)  # [[lang, url], ...]
    internal_links: List[str] = field(default_factory=list)
    inbound_links: Optional[int] = None
    issues: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    error: str = ""
    from_cache: bool = False

    def to_dict(self, full: bool = True) -> Dict[str, Any]:
        """Plain dict. ``full=False`` replaces the link list with a count."""
        data = asdict(self)
        if not full:
            data["internal_link_count"] = len(self.internal_links)
            del data["internal_links"]
            del data["from_cache"]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PageResult:
        """Inverse of ``to_dict(full=True)``; unknown keys are ignored."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def add_issue(self, code: str, note: str = "") -> None:
        """Add an issue once, with an optional explanatory note."""
        if code not in self.issues:
            self.issues.append(code)
        if note:
            self.notes.append(f"{code}: {note}")


@dataclass
class Analysis:
    """Site-wide facts produced by post-processing."""

    robots_url: str = ""
    robots_found: bool = False
    robots_sitemaps: List[str] = field(default_factory=list)
    blocked_count: int = 0
    duplicate_title_groups: int = 0
    orphans: List[str] = field(default_factory=list)
    linked_not_in_sitemap: List[str] = field(default_factory=list)
    hreflang_pages: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Plain dict for JSON output."""
        return asdict(self)
