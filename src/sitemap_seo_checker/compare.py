"""Compare an audit with a previous JSON report to spot regressions and fixes."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from html import escape
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from .models import ERROR, NOTICE, WARNING, PageResult, issue_level

_LEVEL_ORDER = {ERROR: 0, WARNING: 1, NOTICE: 2}


class CompareError(Exception):
    """Raised when the previous report cannot be read or is not a JSON report of this tool."""


@dataclass
class UrlChange:
    """What changed for one URL that is present in both runs."""

    url: str
    new_issues: List[str] = field(default_factory=list)
    fixed_issues: List[str] = field(default_factory=list)
    status_before: Optional[int] = None
    status_after: Optional[int] = None

    @property
    def status_changed(self) -> bool:
        """True when the final status differs between the two runs."""
        return self.status_before != self.status_after


@dataclass
class Comparison:
    """Differences between a previous JSON report and the current results."""

    previous_sitemap: str = ""
    previous_generated_at: str = ""
    previous_total: int = 0
    current_total: int = 0
    added_urls: List[str] = field(default_factory=list)  # audited now, absent before
    removed_urls: List[str] = field(default_factory=list)  # audited before, absent now
    changed: List[UrlChange] = field(default_factory=list)
    new_issue_counts: Dict[str, int] = field(default_factory=dict)
    fixed_issue_counts: Dict[str, int] = field(default_factory=dict)
    unchanged_urls: int = 0

    @property
    def new_error_count(self) -> int:
        """Number of new error-level issues (on changed and on added URLs)."""
        return sum(n for code, n in self.new_issue_counts.items() if issue_level(code) == ERROR)

    @property
    def has_changes(self) -> bool:
        """True when anything differs between the two runs."""
        return bool(self.added_urls or self.removed_urls or self.changed)

    def to_dict(self) -> Dict[str, Any]:
        """Plain dict for JSON output."""
        data = asdict(self)
        data["new_error_count"] = self.new_error_count
        return data


def load_report(path: str) -> Dict[str, Any]:
    """Read a JSON report written with ``--json``. Raises :class:`CompareError`."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise CompareError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise CompareError(f"{path} is not valid JSON: {exc}") from exc
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list) or not all(
        isinstance(p, dict) and isinstance(p.get("url"), str) for p in pages
    ):
        raise CompareError(f"{path} is not a sitemap-seo-checker JSON report (no page list)")
    return data


def _sorted_codes(codes: Any) -> List[str]:
    return sorted(codes, key=lambda c: (_LEVEL_ORDER.get(issue_level(c), 3), c))


def _counts(counter: Counter) -> Dict[str, int]:
    ordered = sorted(
        counter.items(), key=lambda kv: (_LEVEL_ORDER.get(issue_level(kv[0]), 3), -kv[1], kv[0])
    )
    return dict(ordered)


def _status(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _issue_list(value: Any) -> List[str]:
    return [str(i) for i in value] if isinstance(value, list) else []


def compare(previous: Dict[str, Any], results: List[PageResult]) -> Comparison:
    """Diff ``results`` against a report loaded with :func:`load_report`.

    Issues on URLs that are new in this run count as new issues. Issues on URLs
    that left the sitemap are not counted as fixed; the URL is listed as removed.
    """
    before: Dict[str, Dict[str, Any]] = {}
    for page in previous.get("pages", []):
        before.setdefault(page["url"], page)
    current = {page.url: page for page in results}

    out = Comparison(
        previous_sitemap=str(previous.get("sitemap") or ""),
        previous_generated_at=str(previous.get("generated_at") or ""),
        previous_total=len(before),
        current_total=len(current),
        removed_urls=[url for url in before if url not in current],
    )
    new_counts: Counter = Counter()
    fixed_counts: Counter = Counter()
    for url, page in current.items():
        old = before.get(url)
        if old is None:
            out.added_urls.append(url)
            new_counts.update(set(page.issues))
            continue
        old_issues = set(_issue_list(old.get("issues")))
        now_issues = set(page.issues)
        change = UrlChange(
            url=url,
            new_issues=_sorted_codes(now_issues - old_issues),
            fixed_issues=_sorted_codes(old_issues - now_issues),
            status_before=_status(old.get("final_status")),
            status_after=page.final_status,
        )
        if change.new_issues or change.fixed_issues or change.status_changed:
            out.changed.append(change)
            new_counts.update(change.new_issues)
            fixed_counts.update(change.fixed_issues)
        else:
            out.unchanged_urls += 1
    out.changed.sort(
        key=lambda c: (
            -sum(issue_level(i) == ERROR for i in c.new_issues),
            -len(c.new_issues),
            c.url,
        )
    )
    out.new_issue_counts = _counts(new_counts)
    out.fixed_issue_counts = _counts(fixed_counts)
    return out


def _status_text(change: UrlChange) -> str:
    def fmt(value: Optional[int]) -> str:
        return str(value) if value is not None else "ERR"

    if change.status_changed:
        return f"{fmt(change.status_before)} -> {fmt(change.status_after)}"
    return fmt(change.status_after)


def render_comparison(comparison: Comparison, console: Console, limit: int = 15) -> None:
    """Print the comparison tables to ``console``."""
    head = Table(title="Changes since the previous report", show_header=False)
    head.add_row("Previous report", comparison.previous_generated_at or "unknown date")
    head.add_row("URLs before / now", f"{comparison.previous_total} / {comparison.current_total}")
    head.add_row("Added URLs", str(len(comparison.added_urls)))
    head.add_row("Removed URLs", str(len(comparison.removed_urls)))
    head.add_row("URLs with changes", str(len(comparison.changed)))
    head.add_row("New issues", str(sum(comparison.new_issue_counts.values())))
    head.add_row("New errors", str(comparison.new_error_count))
    head.add_row("Fixed issues", str(sum(comparison.fixed_issue_counts.values())))
    console.print(head)
    if not comparison.has_changes:
        console.print("[green]No changes since the previous report.[/green]")
        return

    codes = sorted(
        set(comparison.new_issue_counts) | set(comparison.fixed_issue_counts),
        key=lambda c: (_LEVEL_ORDER.get(issue_level(c), 3), c),
    )
    if codes:
        table = Table(title="Issue changes")
        for col in ("Level", "Issue", "New", "Fixed"):
            table.add_column(col)
        colors = {ERROR: "red", WARNING: "yellow", NOTICE: "cyan"}
        for code in codes:
            level = issue_level(code)
            table.add_row(
                f"[{colors[level]}]{level}[/{colors[level]}]",
                code,
                str(comparison.new_issue_counts.get(code, 0)),
                str(comparison.fixed_issue_counts.get(code, 0)),
            )
        console.print(table)
    if comparison.changed:
        shown = comparison.changed[:limit]
        detail = Table(title=f"Changed URLs (top {len(shown)} of {len(comparison.changed)})")
        for col in ("Status", "URL", "New issues", "Fixed issues"):
            detail.add_column(col, overflow="fold")
        for change in shown:
            detail.add_row(
                _status_text(change),
                change.url,
                ", ".join(change.new_issues) or "-",
                ", ".join(change.fixed_issues) or "-",
            )
        console.print(detail)
    for label, urls in (("Added", comparison.added_urls), ("Removed", comparison.removed_urls)):
        if urls:
            more = f" (+{len(urls) - limit} more)" if len(urls) > limit else ""
            console.print(f"[bold]{label} URLs:[/bold] " + ", ".join(urls[:limit]) + more)


def comparison_html(comparison: Comparison, limit: int = 200) -> str:
    """HTML fragment for the report (heading, counters and tables)."""

    def items(urls: List[str]) -> str:
        return "".join(f"<li>{escape(u)}</li>" for u in urls[:limit]) or "<li>none</li>"

    since = (
        f" since {escape(comparison.previous_generated_at)}"
        if comparison.previous_generated_at
        else ""
    )
    rows = "".join(
        f"<tr><td>{escape(_status_text(c))}</td><td>{escape(c.url)}</td>"
        f"<td>{escape(', '.join(c.new_issues))}</td>"
        f"<td>{escape(', '.join(c.fixed_issues))}</td></tr>"
        for c in comparison.changed[:limit]
    )
    table = (
        "<table><tr><th>Status</th><th>URL</th><th>New issues</th><th>Fixed issues</th></tr>"
        f"{rows}</table>"
        if rows
        else "<p>No URL changed.</p>"
    )
    return (
        f"<h2>Changes{since}</h2>"
        f"<p>{sum(comparison.new_issue_counts.values())} new issue(s) "
        f"({comparison.new_error_count} error-level), "
        f"{sum(comparison.fixed_issue_counts.values())} fixed, "
        f"{len(comparison.changed)} URL(s) changed, {comparison.unchanged_urls} unchanged.</p>"
        f"{table}"
        f"<h3>Added URLs ({len(comparison.added_urls)})</h3><ul>{items(comparison.added_urls)}</ul>"
        f"<h3>Removed URLs ({len(comparison.removed_urls)})</h3>"
        f"<ul>{items(comparison.removed_urls)}</ul>"
    )
