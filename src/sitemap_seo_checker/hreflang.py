"""hreflang validation, including reciprocal (return) links."""

from __future__ import annotations

import re
from typing import Dict, List, Set

from .models import PageResult
from .urls import url_key

_CODE = re.compile(r"^(x-default|[a-z]{2,3}(-[a-z]{4})?(-([a-z]{2}|\d{3}))?)$", re.I)


def validate_hreflang(results: List[PageResult]) -> int:
    """Add hreflang issues to ``results`` in place; return pages that use hreflang.

    Checks: valid codes, a self-reference, one URL per code, and that every
    alternate that was also crawled links back to the page.
    """
    by_key: Dict[str, PageResult] = {}
    for page in results:
        by_key[url_key(page.url)] = page
        if page.final_url:
            by_key[url_key(page.final_url)] = page
    using = 0
    for page in results:
        if not page.hreflang:
            continue
        using += 1
        own: Set[str] = {url_key(page.url)}
        if page.final_url:
            own.add(url_key(page.final_url))
        targets: Dict[str, Set[str]] = {}
        for lang, href in page.hreflang:
            if not _CODE.match(lang):
                page.add_issue("hreflang-invalid-code", f"'{lang}' is not a valid code")
            targets.setdefault(lang.lower(), set()).add(url_key(href))
        if not any(url_key(href) in own for _, href in page.hreflang):
            page.add_issue("hreflang-missing-self", "page does not list itself")
        for lang, keys in targets.items():
            if len(keys) > 1:
                page.add_issue("hreflang-conflict", f"'{lang}' points to {len(keys)} URLs")
        for lang, href in page.hreflang:
            key = url_key(href)
            if key in own or key not in by_key:
                continue
            other = by_key[key]
            if not any(url_key(back) in own for _, back in other.hreflang):
                page.add_issue("hreflang-no-return", f"{lang} -> {href} does not link back")
    return using
