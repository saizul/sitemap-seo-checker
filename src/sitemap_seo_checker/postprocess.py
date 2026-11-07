"""Cross-page analysis applied after all pages are fetched."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from .hreflang import validate_hreflang
from .links import analyze_links
from .models import CROSS_PAGE, Analysis, PageResult
from .robots import RobotsRules


def finalize(
    results: List[PageResult],
    robots: Optional[RobotsRules] = None,
    robots_url: str = "",
    agent: str = "Googlebot",
) -> Analysis:
    """Add duplicate-title, robots, hreflang and orphan issues. Idempotent."""
    analysis = Analysis(robots_url=robots_url, robots_found=robots is not None)
    for page in results:
        page.issues = [i for i in page.issues if i not in CROSS_PAGE]
        page.notes = [n for n in page.notes if n.split(":", 1)[0] not in CROSS_PAGE]
        if page.error:
            continue
        if robots is not None and not robots.is_allowed(agent, page.url):
            page.add_issue("blocked-by-robots", f"disallowed for {agent}")
            analysis.blocked_count += 1
    if robots is not None:
        analysis.robots_sitemaps = list(robots.sitemaps)

    titles: Dict[str, List[PageResult]] = defaultdict(list)
    for page in results:
        if page.is_html and page.final_status == 200 and page.title:
            titles[page.title.casefold()].append(page)
    for group in titles.values():
        if len(group) > 1:
            analysis.duplicate_title_groups += 1
            for page in group:
                page.add_issue("duplicate-title", f"shared with {len(group) - 1} other page(s)")

    analysis.hreflang_pages = validate_hreflang(results)
    analysis.orphans, analysis.linked_not_in_sitemap = analyze_links(results)
    orphan_set = set(analysis.orphans)
    for page in results:
        if page.url in orphan_set:
            page.add_issue("orphan", "no links from other sitemap pages")
    return analysis
