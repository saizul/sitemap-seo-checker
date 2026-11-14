import gzip
import json
from datetime import datetime, timezone
from io import StringIO

import pytest
import responses
from conftest import add_page
from rich.console import Console

from sitemap_seo_checker.cli import main
from sitemap_seo_checker.fetch import FetchError
from sitemap_seo_checker.models import ERROR, NOTICE, WARNING, Analysis, PageResult
from sitemap_seo_checker.report import render_summary, to_html, to_json
from sitemap_seo_checker.sitemap import collect_urls, parse_entries, parse_sitemap
from sitemap_seo_checker.sitemap_lint import (
    MAX_BYTES,
    MAX_ENTRIES,
    MAX_EXAMPLES,
    SITEMAP_ISSUES,
    SitemapEntry,
    SitemapFinding,
    is_absolute_http,
    lint_document,
    parse_w3c_datetime,
    sort_findings,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*entries):
    body = "".join(
        f"<url><loc>{loc}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "") + "</url>"
        for loc, mod in entries
    )
    return f'<?xml version="1.0"?><urlset {NS}>{body}</urlset>'.encode()


def index(*locs):
    body = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f"<sitemapindex {NS}>{body}</sitemapindex>".encode()


def codes(findings):
    return sorted(f.code for f in findings)


def lint(url, entries, kind="urlset", size=100):
    return lint_document(url, kind, [SitemapEntry(*e) for e in entries], size, NOW)


def fake_fetch(mapping):
    def fetch(url):
        if url not in mapping:
            raise FetchError(f"{url}: HTTP 404")
        return mapping[url]

    return fetch


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("2026-03", datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ("2026-03-31", datetime(2026, 3, 31, tzinfo=timezone.utc)),
        ("2026-03-31T10:15Z", datetime(2026, 3, 31, 10, 15, tzinfo=timezone.utc)),
        ("2026-03-31T10:15:30+06:00", datetime(2026, 3, 31, 4, 15, 30, tzinfo=timezone.utc)),
        ("2026-03-31T10:15:30.45-05:00", datetime(2026, 3, 31, 15, 15, 30, tzinfo=timezone.utc)),
        (" 2026-03-31 ", datetime(2026, 3, 31, tzinfo=timezone.utc)),
    ],
)
def test_parse_w3c_datetime_valid(value, expected):
    assert parse_w3c_datetime(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30",  # impossible day
        "2026-13-01",
        "2026-03-31T10:15:30",  # time without a zone
        "2026-03-31 10:15:30Z",  # space instead of T
        "31/03/2026",
        "yesterday",
        "2026-03-31T25:00Z",
        "2026-03-31T10:00+24:00",
        "",
    ],
)
def test_parse_w3c_datetime_invalid(value):
    assert parse_w3c_datetime(value) is None


def test_is_absolute_http():
    assert is_absolute_http("https://example.com/a")
    assert is_absolute_http("http://example.com")
    assert not is_absolute_http("/relative")
    assert not is_absolute_http("ftp://example.com/x")
    assert not is_absolute_http("https://example.com/a b")
    assert not is_absolute_http("https:///nohost")


def test_parse_entries_reads_lastmod_and_size():
    data = urlset(("https://example.com/", "2026-01-01"), ("https://example.com/a", ""))
    kind, entries, size = parse_entries(gzip.compress(data))
    assert kind == "urlset" and size == len(data)
    assert entries == [
        SitemapEntry("https://example.com/", "2026-01-01"),
        SitemapEntry("https://example.com/a", ""),
    ]
    assert parse_sitemap(data) == ("urlset", ["https://example.com/", "https://example.com/a"])


def test_clean_sitemap_has_no_findings():
    assert lint("https://example.com/sitemap.xml", [("https://example.com/a", "2026-06-01")]) == []


def test_invalid_loc_and_lastmod():
    found = lint(
        "https://example.com/sitemap.xml",
        [("/relative", ""), ("https://example.com/a", "June 2026"), ("https://example.com/b", "")],
    )
    assert codes(found) == ["invalid-lastmod", "invalid-loc"]
    by_code = {f.code: f for f in found}
    assert by_code["invalid-loc"].examples == ["/relative"]
    assert by_code["invalid-lastmod"].examples == ["https://example.com/a (June 2026)"]
    assert by_code["invalid-loc"].level == ERROR and by_code["invalid-lastmod"].level == WARNING


def test_future_lastmod_allows_one_day_of_clock_skew():
    url = "https://example.com/sitemap.xml"
    assert lint(url, [("https://example.com/a", "2026-06-16T11:00Z")]) == []
    assert codes(lint(url, [("https://example.com/a", "2026-06-17")])) == ["future-lastmod"]


def test_off_host_and_out_of_scope():
    found = lint(
        "https://example.com/blog/sitemap.xml",
        [
            ("https://example.com/blog/post", ""),
            ("https://example.com/shop/item", ""),
            ("https://www.example.com/blog/x", ""),
            ("https://EXAMPLE.com/blog/y", ""),
        ],
    )
    by_code = {f.code: f for f in found}
    assert set(by_code) == {"off-host", "out-of-scope"}
    assert by_code["off-host"].examples == ["https://www.example.com/blog/x"]
    assert by_code["out-of-scope"].examples == ["https://example.com/shop/item"]
    assert by_code["out-of-scope"].level == NOTICE


def test_index_children_are_not_scope_checked():
    found = lint(
        "https://example.com/sitemaps/index.xml",
        [("https://example.com/post-sitemap.xml", "")],
        kind="index",
    )
    assert found == []


def test_relative_sitemap_url_skips_host_checks():
    assert lint("sitemap.xml", [("https://example.com/a", "")]) == []


def test_limits_and_empty_sitemap():
    url = "https://example.com/sitemap.xml"
    many = [(f"https://example.com/p{i}", "") for i in range(MAX_ENTRIES + 1)]
    found = lint(url, many, size=MAX_BYTES + 1)
    assert codes(found) == ["too-large", "too-many-entries"]
    assert "50,001" in next(f for f in found if f.code == "too-many-entries").detail
    assert codes(lint(url, [])) == ["empty-sitemap"]
    assert lint(url, [], kind="index") == []


def test_long_loc_and_example_cap():
    url = "https://example.com/sitemap.xml"
    long_loc = "https://example.com/" + "a" * 2100
    found = lint(url, [(long_loc, "")] + [(f"/r{i}", "") for i in range(12)])
    by_code = {f.code: f for f in found}
    assert by_code["loc-too-long"].examples[0].endswith("...")
    assert by_code["invalid-loc"].count == 12
    assert len(by_code["invalid-loc"].examples) == MAX_EXAMPLES


def test_collect_reports_duplicates_and_nested_index():
    mapping = {
        "https://example.com/index.xml": index(
            "https://example.com/inner.xml", "https://example.com/b.xml"
        ),
        "https://example.com/inner.xml": index("https://example.com/a.xml"),
        "https://example.com/a.xml": urlset(("https://example.com/x", "")),
        "https://example.com/b.xml": urlset(
            ("https://example.com/x", ""), ("https://example.com/y", "2030-01-01")
        ),
    }
    col = collect_urls(fake_fetch(mapping), "https://example.com/index.xml", now=NOW)
    assert col.urls == ["https://example.com/x", "https://example.com/y"]
    found = {(f.sitemap.rsplit("/", 1)[-1], f.code): f for f in col.findings}
    assert set(found) == {
        ("inner.xml", "nested-index"),
        ("b.xml", "duplicate-loc"),
        ("b.xml", "future-lastmod"),
    }
    assert found[("b.xml", "duplicate-loc")].examples == ["https://example.com/x"]


def test_duplicates_in_one_file_are_grouped():
    data = urlset(*[("https://example.com/a", "")] * 4)
    col = collect_urls(fake_fetch({"https://example.com/s.xml": data}), "https://example.com/s.xml")
    assert [(f.code, f.count) for f in col.findings] == [("duplicate-loc", 3)]


def test_sort_findings_and_codes_have_descriptions():
    items = [
        SitemapFinding("s", "duplicate-loc"),
        SitemapFinding("s", "invalid-lastmod"),
        SitemapFinding("s", "invalid-loc"),
    ]
    assert [f.level for f in sort_findings(items)] == [ERROR, WARNING, NOTICE]
    for level, text in SITEMAP_ISSUES.values():
        assert level in (ERROR, WARNING, NOTICE) and text


def analysis_with_findings():
    return Analysis(
        sitemap_findings=[
            SitemapFinding(
                "https://e.com/s.xml", "invalid-loc", 2, ["/a<b>", "/c"], detail="relative"
            )
        ]
    )


def test_reports_include_findings():
    pages = [PageResult(url="https://e.com/a", final_status=200)]
    data = json.loads(to_json(pages, "https://e.com/s.xml", analysis_with_findings()))
    item = data["analysis"]["sitemap_findings"][0]
    assert item["code"] == "invalid-loc" and item["level"] == ERROR and item["count"] == 2
    html = to_html(pages, "https://e.com/s.xml", analysis_with_findings())
    assert "Sitemap file checks (1)" in html and "/a&lt;b&gt;" in html
    assert "Sitemap file checks" not in to_html(pages, "https://e.com/s.xml", Analysis())
    buf = StringIO()
    render_summary(pages, Console(file=buf, width=160), analysis_with_findings())
    assert "Sitemap file checks" in buf.getvalue() and "invalid-loc" in buf.getvalue()


SITEMAP = "https://example.com/sitemap.xml"


def small_site(mock, sitemap_body):
    mock.add(responses.GET, SITEMAP, body=sitemap_body, content_type="application/xml")
    mock.add(responses.GET, "https://example.com/robots.txt", status=404)
    page = "<html><head><title>T</title><link rel=canonical href='https://example.com/'></head>"
    add_page(mock, "https://example.com/", page + "<body><h1>H</h1></body></html>")


def test_cli_json_includes_findings_and_flag_disables_them(mock, tmp_path, capsys):
    small_site(mock, urlset(("https://example.com/", "not-a-date")))
    base = [SITEMAP, "--json", "--no-progress", "--retries", "0"]
    assert main(base) == 0
    findings = json.loads(capsys.readouterr().out)["analysis"]["sitemap_findings"]
    assert [f["code"] for f in findings] == ["invalid-lastmod"]
    assert main([*base, "--no-sitemap-checks"]) == 0
    assert json.loads(capsys.readouterr().out)["analysis"]["sitemap_findings"] == []


def test_cli_fail_on_errors_counts_sitemap_errors(mock, tmp_path, capsys):
    # The ftp:// entry is filtered out by --include, so only the sitemap finding can cause exit 1.
    args = [SITEMAP, "--no-progress", "--retries", "0", "-o", str(tmp_path / "o.csv")]
    small_site(mock, urlset(("https://example.com/", "")))
    assert main([*args, "--fail-on-errors"]) == 0
    mock.replace(
        responses.GET,
        SITEMAP,
        body=urlset(("https://example.com/", ""), ("ftp://example.com/file", "")),
        content_type="application/xml",
    )
    capsys.readouterr()
    assert main([*args, "--json", "--fail-on-errors", "--include", "^https://"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["level_counts"]["error"] == 0
    assert data["analysis"]["sitemap_findings"][0]["code"] == "invalid-loc"
    assert main([*args, "--fail-on-errors", "--include", "^https://", "--no-sitemap-checks"]) == 0
