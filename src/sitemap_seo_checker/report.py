"""CSV, JSON, HTML and console reports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, List, Optional, TextIO

from rich.console import Console
from rich.table import Table

from . import __version__
from .models import ERROR, ISSUES, NOTICE, WARNING, Analysis, PageResult, issue_level

CSV_COLUMNS = [
    "url", "status", "final_status", "redirects", "final_url", "canonical", "canonical_state",
    "meta_robots", "x_robots_tag", "noindex", "title", "title_length", "meta_description_length",
    "h1_count", "word_count", "response_time_ms", "hreflang_count", "inbound_links", "issues", "error",
]  # fmt: skip


def row_for(page: PageResult) -> Dict[str, Any]:
    """One CSV row."""
    return {
        "url": page.url,
        "status": page.status if page.status is not None else "",
        "final_status": page.final_status if page.final_status is not None else "",
        "redirects": page.redirects,
        "final_url": page.final_url,
        "canonical": page.canonical,
        "canonical_state": page.canonical_state,
        "meta_robots": page.meta_robots,
        "x_robots_tag": page.x_robots_tag,
        "noindex": "yes" if page.noindex else "no",
        "title": page.title,
        "title_length": page.title_length,
        "meta_description_length": page.meta_description_length,
        "h1_count": page.h1_count,
        "word_count": page.word_count if page.word_count >= 0 else "",
        "response_time_ms": page.response_time_ms if page.response_time_ms is not None else "",
        "hreflang_count": len(page.hreflang),
        "inbound_links": page.inbound_links if page.inbound_links is not None else "",
        "issues": ";".join(page.issues),
        "error": page.error,
    }


def write_csv(results: List[PageResult], handle: TextIO) -> None:
    """Write the CSV report to an open text handle (opened with newline='')."""
    writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for page in results:
        writer.writerow(row_for(page))


def summarize(results: List[PageResult]) -> Dict[str, Any]:
    """Aggregate numbers used by every report format."""
    statuses = Counter(str(p.final_status) if p.final_status else "error" for p in results)
    issues = Counter(code for p in results for code in p.issues)
    times = [p.response_time_ms for p in results if p.response_time_ms is not None]
    levels = Counter(issue_level(code) for p in results for code in p.issues)
    return {
        "total_urls": len(results),
        "clean_urls": sum(1 for p in results if not p.issues),
        "urls_with_issues": sum(1 for p in results if p.issues),
        "status_counts": dict(sorted(statuses.items())),
        "issue_counts": dict(sorted(issues.items(), key=lambda kv: (-kv[1], kv[0]))),
        "level_counts": {lvl: levels.get(lvl, 0) for lvl in (ERROR, WARNING, NOTICE)},
        "avg_response_ms": round(sum(times) / len(times)) if times else None,
        "max_response_ms": max(times) if times else None,
    }


def to_json(
    results: List[PageResult], sitemap_url: str, analysis: Optional[Analysis] = None
) -> str:
    """Full JSON report."""
    data = {
        "tool": "sitemap-seo-checker",
        "version": __version__,
        "sitemap": sitemap_url,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summarize(results),
        "analysis": analysis.to_dict() if analysis else {},
        "pages": [p.to_dict(full=False) for p in results],
    }
    return json.dumps(data, indent=2)


def render_summary(
    results: List[PageResult],
    console: Console,
    analysis: Optional[Analysis] = None,
    limit: int = 15,
) -> None:
    """Print the summary tables to ``console``."""
    summary = summarize(results)
    head = Table(title="Sitemap audit summary", show_header=False)
    head.add_row("URLs checked", str(summary["total_urls"]))
    head.add_row("Clean", str(summary["clean_urls"]))
    head.add_row("With issues", str(summary["urls_with_issues"]))
    head.add_row(
        "Avg / max response", f"{summary['avg_response_ms']} / {summary['max_response_ms']} ms"
    )
    head.add_row(
        "Status codes", ", ".join(f"{k}: {v}" for k, v in summary["status_counts"].items()) or "-"
    )
    if analysis is not None:
        head.add_row("robots.txt", "found" if analysis.robots_found else "not found / not checked")
        head.add_row("Orphan pages", str(len(analysis.orphans)))
        head.add_row("Linked, not in sitemap", str(len(analysis.linked_not_in_sitemap)))
    console.print(head)

    if summary["issue_counts"]:
        table = Table(title="Issues")
        for col in ("Level", "Issue", "URLs", "Meaning"):
            table.add_column(col)
        colors = {ERROR: "red", WARNING: "yellow", NOTICE: "cyan"}
        for code, count in summary["issue_counts"].items():
            level = issue_level(code)
            table.add_row(
                f"[{colors[level]}]{level}[/{colors[level]}]",
                code,
                str(count),
                ISSUES.get(code, ("", ""))[1],
            )
        console.print(table)
        worst = sorted(
            (p for p in results if p.issues),
            key=lambda p: (-sum(issue_level(i) == ERROR for i in p.issues), -len(p.issues), p.url),
        )[:limit]
        detail = Table(title=f"URLs needing attention (top {len(worst)})")
        for col in ("Status", "URL", "Issues"):
            detail.add_column(col, overflow="fold")
        for page in worst:
            detail.add_row(str(page.final_status or "ERR"), page.url, ", ".join(page.issues))
        console.print(detail)
    else:
        console.print("[green]No issues found.[/green]")


def to_html(
    results: List[PageResult], sitemap_url: str, analysis: Optional[Analysis] = None
) -> str:
    """Self-contained HTML report."""
    summary = summarize(results)
    colors = {ERROR: "#b91c1c", WARNING: "#b45309", NOTICE: "#0369a1"}
    cards = "".join(
        f'<div class="card" style="border-top:4px solid {colors[lvl]}"><b>{n}</b><span>{lvl}</span></div>'
        for lvl, n in summary["level_counts"].items()
    )
    cards = f'<div class="card"><b>{summary["total_urls"]}</b><span>URLs</span></div>' + cards
    issue_rows = "".join(
        f"<tr><td>{escape(c)}</td><td>{escape(issue_level(c))}</td><td>{n}</td>"
        f"<td>{escape(ISSUES.get(c, ('', ''))[1])}</td></tr>"
        for c, n in summary["issue_counts"].items()
    )
    ordered = sorted(results, key=lambda p: (not p.issues, p.url))
    page_rows = "".join(
        f"<tr><td>{escape(str(p.final_status or 'ERR'))}</td><td>{escape(p.url)}</td>"
        f"<td>{escape(p.title)}</td><td>{escape(p.canonical_state)}</td>"
        f"<td>{escape(', '.join(p.issues))}</td></tr>"
        for p in ordered
    )
    extras = ""
    if analysis is not None:
        orphans = (
            "".join(f"<li>{escape(u)}</li>" for u in analysis.orphans[:200]) or "<li>none</li>"
        )
        extra_links = (
            "".join(f"<li>{escape(u)}</li>" for u in analysis.linked_not_in_sitemap[:200])
            or "<li>none</li>"
        )
        extras = (
            f"<h2>Orphan sitemap pages ({len(analysis.orphans)})</h2><ul>{orphans}</ul>"
            f"<h2>Linked but not in the sitemap ({len(analysis.linked_not_in_sitemap)})</h2><ul>{extra_links}</ul>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Sitemap audit</title><style>"
        "body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:1100px;color:#111}"
        ".cards{display:flex;gap:12px;margin:1rem 0}.card{flex:1;padding:12px;background:#f4f4f5;border-radius:6px;text-align:center}"
        ".card b{display:block;font-size:1.8rem}table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "td,th{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top;word-break:break-all}"
        "</style></head><body>"
        f"<h1>Sitemap audit</h1><p>{escape(sitemap_url)}</p><div class='cards'>{cards}</div>"
        f"<h2>Issues</h2><table><tr><th>Code</th><th>Level</th><th>URLs</th><th>Meaning</th></tr>{issue_rows}</table>"
        f"{extras}<h2>All URLs</h2><table><tr><th>Status</th><th>URL</th><th>Title</th><th>Canonical</th><th>Issues</th></tr>{page_rows}</table>"
        "</body></html>"
    )
