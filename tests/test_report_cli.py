import csv
import gzip
import io
import json
from io import StringIO

import pytest
import responses
from conftest import add_page, fixture_bytes, fixture_text
from rich.console import Console

from sitemap_seo_checker.cli import main
from sitemap_seo_checker.models import Analysis, PageResult
from sitemap_seo_checker.report import (
    CSV_COLUMNS,
    render_summary,
    summarize,
    to_html,
    to_json,
    write_csv,
)

SITEMAP = "https://example.com/sitemap.xml"


def sample_results():
    ok = PageResult(
        url="https://e.com/a",
        status=200,
        final_status=200,
        title="A",
        is_html=True,
        response_time_ms=100,
        canonical_state="self",
    )
    bad = PageResult(
        url="https://e.com/b",
        status=301,
        final_status=404,
        redirects=1,
        response_time_ms=300,
        issues=["non-200", "redirect"],
    )
    err = PageResult(url="https://e.com/c", error="Timeout", issues=["fetch-error"])
    return [ok, bad, err]


def test_csv_columns_and_rows():
    buf = io.StringIO()
    write_csv(sample_results(), buf)
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    assert list(rows[0].keys()) == CSV_COLUMNS and len(rows) == 3
    assert rows[1]["issues"] == "non-200;redirect" and rows[2]["error"] == "Timeout"
    assert rows[0]["noindex"] == "no" and rows[0]["canonical_state"] == "self"


def test_csv_escapes_commas_and_quotes():
    page = PageResult(url="u", title='He said "hi", ok')
    buf = io.StringIO()
    write_csv([page], buf)
    assert next(csv.DictReader(io.StringIO(buf.getvalue())))["title"] == 'He said "hi", ok'


def test_summarize():
    s = summarize(sample_results())
    assert s["total_urls"] == 3 and s["clean_urls"] == 1 and s["urls_with_issues"] == 2
    assert s["status_counts"] == {"200": 1, "404": 1, "error": 1}
    assert s["avg_response_ms"] == 200 and s["level_counts"]["error"] == 2


def test_summarize_empty():
    assert summarize([])["avg_response_ms"] is None


def test_json_report():
    data = json.loads(to_json(sample_results(), SITEMAP, Analysis(orphans=["x"])))
    assert data["sitemap"] == SITEMAP and len(data["pages"]) == 3
    assert "internal_links" not in data["pages"][0] and data["analysis"]["orphans"] == ["x"]


def test_html_report_escapes():
    page = PageResult(
        url="https://e.com/<x>", title="<b>bold</b>", final_status=200, issues=["noindex"]
    )
    out = to_html([page], SITEMAP, Analysis(orphans=["https://e.com/<o>"]))
    assert "<b>bold</b>" not in out and "&lt;b&gt;bold" in out and "&lt;o&gt;" in out
    assert "Orphan sitemap pages (1)" in out


def test_render_summary_text():
    buf = StringIO()
    render_summary(sample_results(), Console(file=buf, width=160), Analysis(robots_found=True))
    out = buf.getvalue()
    assert "non-200" in out and "URLs needing attention" in out and "found" in out


def test_render_summary_clean():
    buf = StringIO()
    render_summary([PageResult(url="u", final_status=200)], Console(file=buf, width=120))
    assert "No issues found" in buf.getvalue()


# --- CLI end to end ---------------------------------------------------------


def site(mock, robots=True):
    mock.add(
        responses.GET,
        SITEMAP,
        body=fixture_bytes("sitemap_index.xml").replace(b"sitemap-posts", b"sitemap-posts"),
        content_type="application/xml",
    )
    mock.add(
        responses.GET,
        "https://example.com/sitemap-posts.xml",
        body=fixture_bytes("sitemap_posts.xml"),
        content_type="application/xml",
    )
    mock.add(
        responses.GET,
        "https://example.com/sitemap-pages.xml.gz",
        body=gzip.compress(fixture_bytes("sitemap_pages.xml")),
        content_type="application/gzip",
    )
    add_page(
        mock,
        "https://example.com/post-1",
        fixture_text("page_good.html").replace("Good   Page", "One"),
    )
    add_page(mock, "https://example.com/post-2", fixture_text("page_noindex.html"))
    add_page(
        mock,
        "https://example.com/",
        fixture_text("page_good.html")
        .replace("Good   Page", "Home")
        .replace('href="/other"', 'href="/post-1"'),
    )
    if robots:
        mock.add(
            responses.GET,
            "https://example.com/robots.txt",
            body="User-agent: *\nDisallow: /post-2\n",
            content_type="text/plain",
        )
    else:
        mock.add(responses.GET, "https://example.com/robots.txt", status=404)


def run(args, tmp_path):
    return main(
        [SITEMAP, "--no-progress", "--retries", "0", "-o", str(tmp_path / "out.csv"), *args]
    )


def test_cli_summary_and_csv(mock, tmp_path, capsys):
    site(mock)
    assert run([], tmp_path) == 0
    out = capsys.readouterr().out
    assert "Sitemap audit summary" in out and "CSV written" in out
    rows = list(csv.DictReader(open(tmp_path / "out.csv", newline="")))
    assert len(rows) == 3
    by_url = {r["url"]: r for r in rows}
    assert "noindex" in by_url["https://example.com/post-2"]["issues"]
    assert "blocked-by-robots" in by_url["https://example.com/post-2"]["issues"]


def test_cli_json(mock, tmp_path, capsys):
    site(mock)
    assert main([SITEMAP, "--json", "--no-progress", "--retries", "0"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["total_urls"] == 3 and data["analysis"]["blocked_count"] == 1
    assert not (tmp_path / "sitemap-report.csv").exists()


def test_cli_no_robots(mock, tmp_path, capsys):
    site(mock)
    run(["--json", "--no-robots"], tmp_path)
    assert json.loads(capsys.readouterr().out)["analysis"]["robots_found"] is False


def test_cli_max_urls(mock, tmp_path, capsys):
    site(mock, robots=False)
    run(["--json", "--max-urls", "2"], tmp_path)
    assert json.loads(capsys.readouterr().out)["summary"]["total_urls"] == 2


def test_cli_html_report(mock, tmp_path):
    site(mock)
    assert run(["--html", str(tmp_path / "r.html")], tmp_path) == 0
    assert "Sitemap audit" in (tmp_path / "r.html").read_text()


def test_cli_fail_on_errors(mock, tmp_path):
    site(mock)
    assert run(["--fail-on-errors"], tmp_path) == 1


def test_cli_resume_flow(mock, tmp_path, capsys):
    site(mock)
    db = str(tmp_path / "c.db")
    run(["--cache", db, "--json"], tmp_path)
    capsys.readouterr()
    mock.calls.reset()
    run(["--cache", db, "--resume", "--json"], tmp_path)
    data = json.loads(capsys.readouterr().out)
    page_fetches = [
        c for c in mock.calls if "/post-" in c.request.url or c.request.url.endswith("example.com/")
    ]
    assert page_fetches == [] and data["summary"]["total_urls"] == 3


def test_cli_resume_requires_cache(capsys):
    assert main([SITEMAP, "--resume"]) == 2


def test_cli_bad_workers(capsys):
    assert main([SITEMAP, "--workers", "0"]) == 2


def test_cli_unreachable_sitemap(mock, tmp_path, capsys):
    mock.add(responses.GET, SITEMAP, status=404)
    assert run([], tmp_path) == 2
    assert "cannot read sitemap" in capsys.readouterr().err


def test_cli_empty_sitemap(mock, tmp_path, capsys):
    mock.add(
        responses.GET,
        SITEMAP,
        body=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
    )
    assert run([], tmp_path) == 2


def test_cli_unwritable_output(mock, tmp_path, capsys):
    site(mock)
    assert (
        main([SITEMAP, "--no-progress", "--retries", "0", "-o", str(tmp_path / "nodir" / "x.csv")])
        == 2
    )


def test_cli_user_agent_sent(mock, tmp_path):
    site(mock)
    run(["--user-agent", "my-audit-bot"], tmp_path)
    assert all(c.request.headers["User-Agent"] == "my-audit-bot" for c in mock.calls)


def test_cli_delay_option_accepted(mock, tmp_path):
    site(mock)
    assert run(["--delay", "0", "--workers", "2"], tmp_path) == 0


@pytest.mark.parametrize(
    "flags, message",
    [
        (["--timeout", "0"], "--timeout must be greater than 0"),
        (["--timeout", "-3"], "--timeout must be greater than 0"),
        (["--timeout", "nan"], "--timeout must be greater than 0"),
        (["--delay", "-1"], "--delay must not be negative"),
        (["--retries", "-1"], "--retries must not be negative"),
        (["--max-urls", "0"], "--max-urls must be at least 1"),
    ],
)
def test_cli_rejects_out_of_range_options(flags, message, capsys):
    assert main([SITEMAP, *flags]) == 2
    assert message in capsys.readouterr().err
