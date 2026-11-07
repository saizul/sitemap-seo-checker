"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from . import __version__
from .cache import Cache
from .crawler import crawl
from .fetch import DEFAULT_USER_AGENT, Fetcher
from .models import ERROR, PageResult, issue_level
from .postprocess import finalize
from .report import render_summary, to_html, to_json, write_csv
from .robots import load_robots
from .sitemap import SitemapError, collect_urls


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    p = argparse.ArgumentParser(
        prog="sitemap-check",
        description="Audit every URL in an XML sitemap (index and .gz supported).",
    )
    p.add_argument("sitemap_url", help="URL of sitemap.xml, a sitemap index or a .xml.gz file")
    p.add_argument("--workers", type=int, default=5, help="concurrent requests (default 5)")
    p.add_argument(
        "--delay", type=float, default=0.0, help="seconds each worker waits before a request"
    )
    p.add_argument("--max-urls", type=int, default=None, help="stop after this many URLs")
    p.add_argument("--timeout", type=float, default=15.0, help="request timeout in seconds")
    p.add_argument("--retries", type=int, default=1, help="retries on timeouts/429/5xx (default 1)")
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header")
    p.add_argument("-o", "--output", metavar="CSV", help="CSV path (default sitemap-report.csv)")
    p.add_argument(
        "--json", action="store_true", help="print JSON to stdout instead of the summary"
    )
    p.add_argument("--html", metavar="PATH", help="also write an HTML report")
    p.add_argument("--cache", metavar="DB", help="SQLite file that stores finished URLs")
    p.add_argument(
        "--resume", action="store_true", help="reuse results from --cache for this sitemap"
    )
    p.add_argument("--no-robots", action="store_true", help="do not read robots.txt")
    p.add_argument(
        "--robots-agent",
        default="Googlebot",
        help="agent used for robots rules (default Googlebot)",
    )
    p.add_argument("--no-progress", action="store_true", help="hide the progress bar")
    p.add_argument(
        "--fail-on-errors", action="store_true", help="exit 1 if any error-level issue exists"
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point. Exit codes: 0 ok, 1 errors (--fail-on-errors), 2 failure, 130 interrupted."""
    args = build_parser().parse_args(argv)
    err = Console(stderr=True)
    if args.workers < 1:
        print("error: --workers must be at least 1", file=sys.stderr)
        return 2
    if args.resume and not args.cache:
        print("error: --resume needs --cache", file=sys.stderr)
        return 2
    fetcher = Fetcher(
        user_agent=args.user_agent, timeout=args.timeout, delay=args.delay, retries=args.retries
    )
    try:
        collection = collect_urls(fetcher.get_bytes, args.sitemap_url, args.max_urls)
    except SitemapError as exc:
        print(f"error: cannot read sitemap: {exc}", file=sys.stderr)
        return 2
    for message in collection.errors:
        err.print(f"[yellow]warning:[/yellow] {message}")
    if not collection.urls:
        print("error: the sitemap contains no URLs", file=sys.stderr)
        return 2

    robots, robots_url = (None, "")
    if not args.no_robots:
        robots, robots_url = load_robots(fetcher, args.sitemap_url)

    cache = Cache(args.cache) if args.cache else None
    show = not args.no_progress and err.is_terminal
    progress = Progress(
        TextColumn("[bold]Checking"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(), console=err, disable=not show, transient=True,
    )  # fmt: skip
    task = progress.add_task("crawl", total=len(collection.urls))

    def on_progress(done: int, total: int, page: PageResult) -> None:
        progress.update(task, completed=done)

    try:
        with progress:
            results = crawl(
                collection.urls, fetcher, workers=args.workers, cache=cache,
                run_key=args.sitemap_url, resume=args.resume, on_progress=on_progress,
            )  # fmt: skip
    except KeyboardInterrupt:
        hint = f" Re-run with --cache {args.cache} --resume to continue." if cache else ""
        print(f"\ninterrupted.{hint}", file=sys.stderr)
        return 130
    finally:
        if cache is not None:
            cache.close()

    analysis = finalize(results, robots, robots_url, args.robots_agent)
    if collection.truncated:
        err.print(
            f"[yellow]note:[/yellow] limited to {args.max_urls} URLs; orphan results may be partial"
        )

    output = args.output or (None if args.json else "sitemap-report.csv")
    try:
        if output:
            with open(output, "w", newline="", encoding="utf-8") as handle:
                write_csv(results, handle)
        if args.html:
            with open(args.html, "w", encoding="utf-8") as handle:
                handle.write(to_html(results, args.sitemap_url, analysis))
    except OSError as exc:
        print(f"error: cannot write report: {exc.strerror}", file=sys.stderr)
        return 2

    if args.json:
        print(to_json(results, args.sitemap_url, analysis))
    else:
        render_summary(results, Console(width=140), analysis)
        if output:
            print(f"CSV written to {output}")
    if args.fail_on_errors and any(issue_level(i) == ERROR for p in results for i in p.issues):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
