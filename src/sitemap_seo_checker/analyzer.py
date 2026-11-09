"""Turn one HTTP response into a :class:`PageResult`."""

from __future__ import annotations

import re
from typing import List, Union

from bs4 import BeautifulSoup

from .fetch import Fetcher
from .models import PageResult
from .urls import absolutize, host_key, url_key

TITLE_MAX = 60
DESCRIPTION_MAX = 160
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_LINKS = 5000
_NOINDEX = re.compile(r"\b(noindex|none)\b", re.I)
SHORT_BODY_WORDS = 250  # "not found" wording in the body only counts on pages this short
_NOT_FOUND = re.compile(
    r"\b404\s*(?:error|page|not\s+found)|\berror\s*404\b|\bnot\s+found\b"
    r"|\b(?:can(?:no|['\u2019]?)t|could\s*n[o']?t)\s+be\s+found\b"
    r"|\bdoes(?:\s+not|n['\u2019]t)\s+exist\b|\bno\s+longer\s+(?:available|exists?)\b"
    r"|\bpage\s+you\s+(?:are|were)\s+looking\s+for\b"
    r"|\u09aa\u09be\u0993\u09af\u09bc\u09be\s+\u09af\u09be\u09af\u09bc\u09a8\u09bf",  # Bangla
    re.I,
)
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def apply_html(result: PageResult, html: Union[str, bytes]) -> None:
    """Fill the HTML-derived fields of ``result`` (title, canonical, links, ...).

    ``result.final_url`` (or ``result.url``) is the base for relative URLs.
    """
    base = result.final_url or result.url
    soup = BeautifulSoup(html, "html.parser")
    result.is_html = True
    result.title = _squash(soup.title.get_text()) if soup.title else ""
    result.title_length = len(result.title)
    description = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    result.meta_description_length = (
        len(_squash(str(description.get("content", "")))) if description else 0
    )
    result.h1_count = len(soup.find_all("h1"))

    robots_values: List[str] = []
    for meta in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)}):
        robots_values.append(_squash(str(meta.get("content", ""))))
    result.meta_robots = ", ".join(v for v in robots_values if v)

    canonical = ""
    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        rel = [rel] if isinstance(rel, str) else rel
        if "canonical" in [r.lower() for r in rel]:
            canonical = absolutize(base, str(link["href"])) if str(link["href"]).strip() else ""
            break
    result.canonical = canonical
    if not canonical:
        result.canonical_state = "missing"
    elif url_key(canonical) in {url_key(result.url), url_key(base)}:
        result.canonical_state = "self"
    else:
        result.canonical_state = "other"

    hreflang: List[List[str]] = []
    for link in soup.find_all("link", href=True, hreflang=True):
        rel = link.get("rel") or []
        rel = [rel] if isinstance(rel, str) else rel
        if "alternate" in [r.lower() for r in rel]:
            hreflang.append([str(link["hreflang"]).strip(), absolutize(base, str(link["href"]))])
    result.hreflang = hreflang

    site = host_key(base)
    links: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith("#") or href.lower().startswith(_SKIP_SCHEMES):
            continue
        target = absolutize(base, href)
        if not target.lower().startswith(("http://", "https://")) or host_key(target) != site:
            continue
        key = url_key(target)
        if key not in seen and key != url_key(base):
            seen.add(key)
            links.append(target)
        if len(links) >= MAX_LINKS:
            break
    result.internal_links = links

    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    body_text = _squash(soup.get_text(" "))
    result.word_count = len(body_text.split())
    result.soft_404_hint = _soft_404_hint(result, soup, body_text)


def _soft_404_hint(result: PageResult, soup: BeautifulSoup, body_text: str) -> str:
    """First "not found" wording in the title, an H1, or (on short pages) the body."""
    heading = soup.find("h1")
    candidates = [("title", result.title), ("h1", _squash(heading.get_text()) if heading else "")]
    if result.word_count <= SHORT_BODY_WORDS:
        candidates.append(("body", body_text))
    for where, text in candidates:
        match = _NOT_FOUND.search(text)
        if match:
            return f"{where} says '{match.group(0).lower()}'"
    return ""


def soft_404_reason(result: PageResult, min_words: int = 0) -> str:
    """Why a 200 HTML page looks like a soft 404, or "" if it does not.

    ``min_words`` > 0 also flags pages whose visible text is shorter than that.
    """
    if not result.is_html or result.final_status != 200 or result.noindex:
        return ""
    if result.soft_404_hint:
        return result.soft_404_hint
    if min_words > 0 and 0 <= result.word_count < min_words:
        return f"only {result.word_count} words (minimum {min_words})"
    return ""


def page_issues(result: PageResult, soft_404_min_words: int = 0) -> List[str]:
    """Issues that can be decided from a single page."""
    issues: List[str] = []
    if result.error:
        return ["fetch-error"]
    if result.final_status != 200:
        issues.append("non-200")
    if result.redirects:
        issues.append("redirect")
    if result.noindex:
        issues.append("noindex")
    if soft_404_reason(result, soft_404_min_words):
        issues.append("soft-404")
    if result.is_html and result.final_status == 200:
        if result.canonical_state == "other":
            issues.append("canonical-other")
        elif result.canonical_state == "missing":
            issues.append("canonical-missing")
        if not result.title:
            issues.append("missing-title")
        elif result.title_length > TITLE_MAX:
            issues.append("title-too-long")
        if result.h1_count == 0:
            issues.append("missing-h1")
        elif result.h1_count > 1:
            issues.append("multiple-h1")
        if result.meta_description_length == 0:
            issues.append("missing-description")
        elif result.meta_description_length > DESCRIPTION_MAX:
            issues.append("description-too-long")
    return issues


def analyze(url: str, fetcher: Fetcher, soft_404_min_words: int = 0) -> PageResult:
    """Fetch ``url`` and describe it. Never raises."""
    result = PageResult(url=url)
    try:
        fetched = fetcher.fetch(url)
        if fetched.response is None:
            result.error = fetched.error
            result.issues = page_issues(result)
            return result
        resp = fetched.response
        try:
            result.response_time_ms = round(fetched.elapsed_ms)
            result.redirects = len(resp.history)
            result.status = resp.history[0].status_code if resp.history else resp.status_code
            result.final_status = resp.status_code
            result.final_url = resp.url
            result.x_robots_tag = resp.headers.get("X-Robots-Tag", "")
            result.content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            body = b""
            if "html" in result.content_type and resp.status_code < 400:
                for chunk in resp.iter_content(65536):
                    body += chunk
                    if len(body) >= MAX_BODY_BYTES:
                        break
        finally:
            resp.close()
        if body:
            apply_html(result, body)
        result.noindex = bool(
            _NOINDEX.search(result.meta_robots) or _NOINDEX.search(result.x_robots_tag)
        )
        result.issues = page_issues(result, soft_404_min_words)
        if "soft-404" in result.issues:
            result.add_issue("soft-404", soft_404_reason(result, soft_404_min_words))
    except Exception as exc:  # one bad page must never abort the crawl
        result.error = f"{exc.__class__.__name__}: {exc}"[:200]
        result.issues = ["fetch-error"]
    return result
