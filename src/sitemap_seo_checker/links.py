"""Internal link analysis: orphan sitemap pages and linked pages missing from the sitemap."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .models import PageResult
from .urls import is_page_like, url_key


def analyze_links(results: List[PageResult]) -> Tuple[List[str], List[str]]:
    """Return ``(orphan_urls, linked_but_not_in_sitemap)`` and set ``inbound_links``.

    Only pages that were fetched as HTML with status 200 take part. A sitemap
    page is an orphan when no *other* crawled sitemap page links to it. With
    fewer than two such pages the analysis is skipped.
    """
    pages = [p for p in results if p.is_html and p.final_status == 200]
    if len(pages) < 2:
        return [], []
    owner: Dict[str, PageResult] = {}
    for page in results:
        owner[url_key(page.url)] = page
        if page.final_url:
            owner[url_key(page.final_url)] = page
    inbound: Dict[int, int] = {id(p): 0 for p in results}
    unknown: Dict[str, str] = {}
    for page in pages:
        counted = set()
        own = {url_key(page.url), url_key(page.final_url or page.url)}
        for link in page.internal_links:
            key = url_key(link)
            if key in own:
                continue
            target = owner.get(key)
            if target is None:
                if is_page_like(link):
                    unknown.setdefault(key, link)
            elif id(target) not in counted:
                counted.add(id(target))
                inbound[id(target)] += 1
    orphans: List[str] = []
    html_ids = {id(p) for p in pages}
    for page in results:
        in_scope = id(page) in html_ids
        page.inbound_links = inbound[id(page)] if in_scope else None
        if in_scope and inbound[id(page)] == 0:
            orphans.append(page.url)
    return orphans, sorted(unknown.values())
