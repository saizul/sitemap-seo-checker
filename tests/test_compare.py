import json
from io import StringIO

import pytest
from rich.console import Console
from test_report_cli import SITEMAP, site

from sitemap_seo_checker.cli import main
from sitemap_seo_checker.compare import (
    CompareError,
    Comparison,
    UrlChange,
    compare,
    comparison_html,
    load_report,
    render_comparison,
)
from sitemap_seo_checker.models import Analysis, PageResult
from sitemap_seo_checker.report import to_html, to_json


def page(url, status=200, issues=()):
    return PageResult(url=url, status=status, final_status=status, issues=list(issues))


def report(pages):
    """A previous report as produced by ``--json`` (round-tripped through JSON)."""
    return json.loads(to_json(pages, SITEMAP, Analysis()))


def previous_pages():
    return [
        page("https://e.com/a"),
        page("https://e.com/b", issues=["missing-description", "redirect"]),
        page("https://e.com/c", issues=["noindex"]),
        page("https://e.com/gone", status=404, issues=["non-200"]),
    ]


def current_pages():
    return [
        page("https://e.com/a", status=404, issues=["non-200", "missing-title"]),
        page("https://e.com/b", issues=["missing-description"]),
        page("https://e.com/c", issues=["noindex"]),
        page("https://e.com/new", issues=["canonical-other", "orphan"]),
    ]


# --- compare() --------------------------------------------------------------


def test_compare_finds_new_fixed_added_and_removed():
    result = compare(report(previous_pages()), current_pages())
    assert result.previous_total == 4 and result.current_total == 4
    assert result.added_urls == ["https://e.com/new"]
    assert result.removed_urls == ["https://e.com/gone"]
    assert result.unchanged_urls == 1
    assert [c.url for c in result.changed] == ["https://e.com/a", "https://e.com/b"]
    a, b = result.changed
    assert a.new_issues == ["non-200", "missing-title"] and a.fixed_issues == []
    assert (a.status_before, a.status_after, a.status_changed) == (200, 404, True)
    assert b.new_issues == [] and b.fixed_issues == ["redirect"] and not b.status_changed


def test_issues_on_added_urls_count_as_new_but_removed_urls_are_not_fixed():
    result = compare(report(previous_pages()), current_pages())
    assert result.new_issue_counts == {
        "canonical-other": 1,
        "non-200": 1,
        "missing-title": 1,
        "orphan": 1,
    }
    assert result.fixed_issue_counts == {"redirect": 1}
    assert result.new_error_count == 2


def test_new_issue_counts_are_ordered_by_level_then_count():
    current = [
        page("https://e.com/1", issues=["orphan", "noindex"]),
        page("https://e.com/2", issues=["orphan", "multiple-h1"]),
    ]
    result = compare(report([page("https://e.com/1"), page("https://e.com/2")]), current)
    assert list(result.new_issue_counts.items()) == [
        ("noindex", 1),
        ("orphan", 2),
        ("multiple-h1", 1),
    ]


def test_identical_runs_have_no_changes():
    result = compare(report(previous_pages()), previous_pages())
    assert not result.has_changes and result.unchanged_urls == 4
    assert result.new_issue_counts == {} and result.new_error_count == 0


def test_status_change_alone_is_a_change():
    before = report([page("https://e.com/a", status=200)])
    failed = PageResult(url="https://e.com/a", error="Timeout")
    result = compare(before, [failed])
    assert len(result.changed) == 1
    assert result.changed[0].status_before == 200 and result.changed[0].status_after is None


def test_changed_urls_are_sorted_with_new_errors_first():
    before = report([page(f"https://e.com/{n}") for n in "abc"])
    current = [
        page("https://e.com/a", issues=["orphan"]),
        page("https://e.com/b", issues=["missing-h1", "missing-title"]),
        page("https://e.com/c", issues=["noindex"]),
    ]
    assert [c.url[-1] for c in compare(before, current).changed] == ["c", "b", "a"]


def test_compare_tolerates_sparse_and_duplicate_previous_pages():
    previous = {
        "pages": [
            {"url": "https://e.com/a", "final_status": 200},
            {"url": "https://e.com/a", "issues": ["noindex"]},
            {"url": "https://e.com/b", "issues": "oops", "final_status": "200"},
        ]
    }
    result = compare(previous, [page("https://e.com/a"), page("https://e.com/b", status=None)])
    assert result.previous_total == 2 and result.previous_generated_at == ""
    assert result.changed == [] and result.unchanged_urls == 2


def test_comparison_to_dict_is_json_serialisable():
    data = json.loads(json.dumps(compare(report(previous_pages()), current_pages()).to_dict()))
    assert data["new_error_count"] == 2 and data["previous_sitemap"] == SITEMAP
    assert data["changed"][0]["new_issues"] == ["non-200", "missing-title"]
    assert data["changed"][0]["status_before"] == 200


# --- load_report() ----------------------------------------------------------


def test_load_report_round_trip(tmp_path):
    path = tmp_path / "prev.json"
    path.write_text(to_json(previous_pages(), SITEMAP), encoding="utf-8")
    data = load_report(str(path))
    assert data["sitemap"] == SITEMAP and len(data["pages"]) == 4


@pytest.mark.parametrize(
    "content, message",
    [
        ("{not json", "is not valid JSON"),
        ("[1, 2]", "is not a sitemap-seo-checker JSON report"),
        ('{"pages": "x"}', "is not a sitemap-seo-checker JSON report"),
        ('{"pages": [{"title": "no url"}]}', "is not a sitemap-seo-checker JSON report"),
    ],
)
def test_load_report_rejects_bad_files(tmp_path, content, message):
    path = tmp_path / "prev.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CompareError, match=message):
        load_report(str(path))


def test_load_report_missing_file(tmp_path):
    with pytest.raises(CompareError, match="cannot read"):
        load_report(str(tmp_path / "nope.json"))


# --- rendering --------------------------------------------------------------


def render(comparison, **kwargs):
    buf = StringIO()
    render_comparison(comparison, Console(file=buf, width=200), **kwargs)
    return buf.getvalue()


def test_render_comparison_tables():
    out = render(compare(report(previous_pages()), current_pages()))
    assert "Changes since the previous report" in out and "Issue changes" in out
    assert "200 -> 404" in out and "missing-title" in out and "redirect" in out
    assert "Added URLs: https://e.com/new" in out and "Removed URLs: https://e.com/gone" in out


def test_render_comparison_without_changes():
    out = render(compare(report(previous_pages()), previous_pages()))
    assert "No changes since the previous report" in out and "Issue changes" not in out


def test_render_comparison_limits_long_lists():
    current = [page(f"https://e.com/{n}", issues=["orphan"]) for n in range(5)]
    out = render(compare({"pages": []}, current), limit=2)
    assert "(+3 more)" in out and "https://e.com/4" not in out


def test_render_status_for_fetch_errors():
    change = UrlChange(url="u", new_issues=["fetch-error"], status_before=200, status_after=None)
    out = render(Comparison(changed=[change], new_issue_counts={"fetch-error": 1}))
    assert "200 -> ERR" in out


def test_comparison_html_escapes_and_counts():
    current = [page("https://e.com/<a>", issues=["noindex"]), page("https://e.com/<new>")]
    before = report([page("https://e.com/<a>"), page("https://e.com/<old>")])
    out = comparison_html(compare(before, current))
    assert "<a>" not in out and "&lt;a&gt;" in out and "&lt;new&gt;" in out and "&lt;old&gt;" in out
    assert "1 new issue(s) (1 error-level), 0 fixed" in out
    assert "Added URLs (1)" in out and "Removed URLs (1)" in out


def test_comparison_html_without_changes():
    out = comparison_html(compare(report(previous_pages()), previous_pages()))
    assert "No URL changed." in out and "<li>none</li>" in out


def test_reports_include_comparison_only_when_given():
    comparison = compare(report(previous_pages()), current_pages())
    with_cmp = json.loads(to_json(current_pages(), SITEMAP, Analysis(), comparison))
    assert with_cmp["comparison"]["added_urls"] == ["https://e.com/new"]
    assert "comparison" not in json.loads(to_json(current_pages(), SITEMAP, Analysis()))
    assert "<h2>Changes since" in to_html(current_pages(), SITEMAP, Analysis(), comparison)
    assert "<h2>Changes" not in to_html(current_pages(), SITEMAP, Analysis())


# --- CLI --------------------------------------------------------------------


def run_json(args, capsys):
    code = main([SITEMAP, "--json", "--no-progress", "--retries", "0", *args])
    return code, capsys.readouterr()


def test_cli_compare_identical_run(mock, tmp_path, capsys):
    site(mock)
    code, captured = run_json([], capsys)
    prev = tmp_path / "prev.json"
    prev.write_text(captured.out, encoding="utf-8")
    code, captured = run_json(["--compare", str(prev), "--fail-on-new-errors"], capsys)
    data = json.loads(captured.out)
    assert code == 0
    assert data["comparison"]["changed"] == [] and data["comparison"]["unchanged_urls"] == 3
    assert data["comparison"]["previous_generated_at"]


def test_cli_compare_reports_regressions_and_fixes(mock, tmp_path, capsys):
    site(mock)
    _, captured = run_json([], capsys)
    previous = json.loads(captured.out)
    for entry in previous["pages"]:
        if entry["url"] == "https://example.com/post-2":
            entry["issues"] = ["missing-h1"]  # noindex / blocked-by-robots are new now
    previous["pages"].append({"url": "https://example.com/old", "issues": [], "final_status": 200})
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps(previous), encoding="utf-8")

    code, captured = run_json(["--compare", str(prev)], capsys)
    cmp_data = json.loads(captured.out)["comparison"]
    assert code == 0
    assert cmp_data["removed_urls"] == ["https://example.com/old"]
    changed = {c["url"]: c for c in cmp_data["changed"]}
    post2 = changed["https://example.com/post-2"]
    assert {"noindex", "blocked-by-robots"} <= set(post2["new_issues"])
    assert post2["fixed_issues"] == ["missing-h1"]
    assert cmp_data["new_error_count"] >= 2

    code, _ = run_json(["--compare", str(prev), "--fail-on-new-errors"], capsys)
    assert code == 1


def test_cli_compare_console_and_html(mock, tmp_path, capsys):
    site(mock)
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps({"pages": [{"url": "https://example.com/", "issues": []}]}))
    html = tmp_path / "r.html"
    code = main(
        [SITEMAP, "--no-progress", "--retries", "0", "-o", str(tmp_path / "o.csv")]
        + ["--compare", str(prev), "--html", str(html)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Changes since the previous report" in out and "Added URLs" in out
    assert "Added URLs (2)" in html.read_text(encoding="utf-8")


def test_cli_compare_bad_file_fails_before_crawling(mock, tmp_path, capsys):
    site(mock)
    code, captured = run_json(["--compare", str(tmp_path / "missing.json")], capsys)
    assert code == 2 and "cannot read" in captured.err
    assert len(mock.calls) == 0


def test_cli_fail_on_new_errors_needs_compare(capsys):
    assert main([SITEMAP, "--fail-on-new-errors"]) == 2
    assert "--fail-on-new-errors needs --compare" in capsys.readouterr().err
