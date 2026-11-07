import responses
from conftest import add_page, fixture_text

from sitemap_seo_checker.analyzer import analyze, apply_html, page_issues
from sitemap_seo_checker.models import PageResult


def parse(name, url="https://example.com/good/", final=""):
    page = PageResult(url=url, final_url=final or url, final_status=200)
    apply_html(page, fixture_text(name))
    return page


def test_title_whitespace_collapsed():
    page = parse("page_good.html")
    assert page.title == "Good Page Title" and page.title_length == 15


def test_description_and_h1():
    page = parse("page_good.html")
    assert page.meta_description_length == len("A perfectly fine description of the page.")
    assert page.h1_count == 1


def test_canonical_self():
    page = parse("page_good.html")
    assert page.canonical_state == "self" and page.canonical == "https://example.com/good/"


def test_canonical_self_trailing_slash_insensitive():
    assert parse("page_good.html", url="https://example.com/good").canonical_state == "self"


def test_canonical_other():
    page = parse("page_canonical_other.html", url="https://example.com/dup")
    assert page.canonical_state == "other"
    assert "canonical-other" in page_issues(page)
    assert page.h1_count == 2 and "multiple-h1" in page_issues(page)


def test_canonical_missing_and_bare_page():
    page = parse("page_bare.html")
    assert page.canonical_state == "missing"
    issues = page_issues(page)
    assert {"canonical-missing", "missing-title", "missing-h1", "missing-description"} <= set(
        issues
    )


def test_relative_canonical_resolved():
    page = parse("page_noindex.html", url="https://example.com/hidden")
    assert page.canonical == "https://example.com/hidden" and page.canonical_state == "self"


def test_meta_robots_captured():
    page = parse("page_noindex.html", url="https://example.com/hidden")
    assert page.meta_robots == "noindex, follow"


def test_internal_links_filtered():
    page = parse("page_good.html")
    assert page.internal_links == [
        "https://example.com/other",
        "https://example.com/third",
        "https://example.com/logo.png",
    ]


def test_hreflang_extracted():
    page = parse("page_hreflang_en.html", url="https://example.com/en")
    assert page.hreflang == [
        ["en", "https://example.com/en"],
        ["fr", "https://example.com/fr"],
        ["x-default", "https://example.com/en"],
    ]


def test_title_too_long_and_description_too_long():
    page = PageResult(url="u", final_url="u", final_status=200)
    apply_html(
        page, f"<title>{'a' * 61}</title><meta name='description' content='{'b' * 161}'><h1>x</h1>"
    )
    assert {"title-too-long", "description-too-long"} <= set(page_issues(page))


def test_analyze_ok_page(mock, fetcher):
    add_page(mock, "https://example.com/good/", fixture_text("page_good.html"))
    page = analyze("https://example.com/good/", fetcher)
    assert (page.status, page.final_status, page.redirects) == (200, 200, 0)
    assert page.response_time_ms is not None and page.is_html
    assert "non-200" not in page.issues and page.content_type == "text/html"


def test_analyze_redirect(mock, fetcher):
    mock.add(
        responses.GET,
        "https://example.com/old",
        status=301,
        headers={"Location": "https://example.com/new"},
    )
    add_page(mock, "https://example.com/new", fixture_text("page_good.html"))
    page = analyze("https://example.com/old", fetcher)
    assert page.status == 301 and page.final_status == 200 and page.redirects == 1
    assert page.final_url == "https://example.com/new" and "redirect" in page.issues


def test_analyze_404(mock, fetcher):
    add_page(mock, "https://example.com/gone", "<title>x</title>", status=404)
    page = analyze("https://example.com/gone", fetcher)
    assert page.final_status == 404 and "non-200" in page.issues
    assert page.title == ""  # error pages are not parsed


def test_analyze_noindex_meta(mock, fetcher):
    add_page(mock, "https://example.com/hidden", fixture_text("page_noindex.html"))
    page = analyze("https://example.com/hidden", fetcher)
    assert page.noindex and "noindex" in page.issues


def test_analyze_x_robots_tag(mock, fetcher):
    add_page(
        mock,
        "https://example.com/x",
        fixture_text("page_good.html"),
        headers={"X-Robots-Tag": "googlebot: noindex"},
    )
    page = analyze("https://example.com/x", fetcher)
    assert page.noindex and page.x_robots_tag == "googlebot: noindex"


def test_analyze_non_html_not_parsed(mock, fetcher):
    add_page(mock, "https://example.com/a.pdf", b"%PDF-1.4", content_type="application/pdf")
    page = analyze("https://example.com/a.pdf", fetcher)
    assert not page.is_html and page.title == "" and "missing-title" not in page.issues


def test_analyze_connection_error(mock, fetcher):
    page = analyze("https://example.com/down", fetcher)
    assert page.error and page.issues == ["fetch-error"]


def test_analyze_never_raises(fetcher, monkeypatch):
    monkeypatch.setattr(fetcher, "fetch", lambda url: 1 / 0)
    page = analyze("https://example.com/", fetcher)
    assert "ZeroDivisionError" in page.error


def test_page_result_roundtrip():
    page = PageResult(
        url="u", title="t", hreflang=[["en", "x"]], internal_links=["a"], issues=["noindex"]
    )
    clone = PageResult.from_dict(page.to_dict())
    assert clone == page
    assert "internal_links" not in page.to_dict(full=False)
    assert PageResult.from_dict({"url": "u", "mystery": 1}).url == "u"
