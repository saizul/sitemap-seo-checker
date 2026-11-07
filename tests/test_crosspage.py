from sitemap_seo_checker.hreflang import validate_hreflang
from sitemap_seo_checker.links import analyze_links
from sitemap_seo_checker.models import PageResult
from sitemap_seo_checker.postprocess import finalize
from sitemap_seo_checker.robots import RobotsRules
from sitemap_seo_checker.urls import absolutize, host_key, is_page_like, url_key


def page(url, title="T", links=(), hreflang=(), status=200, html=True):
    return PageResult(
        url=url,
        final_url=url,
        status=status,
        final_status=status,
        is_html=html,
        title=title,
        internal_links=list(links),
        hreflang=[list(h) for h in hreflang],
    )


# --- url helpers
def test_url_key_ignores_scheme_www_slash_fragment():
    assert url_key("http://www.Example.com/a/") == url_key("https://example.com/a")
    assert url_key("https://e.com/a?x=1") != url_key("https://e.com/a")


def test_host_key_and_absolutize():
    assert host_key("https://WWW.example.com:443/") == "example.com"
    assert absolutize("https://e.com/a/b", "../c#frag") == "https://e.com/c"


def test_is_page_like():
    assert is_page_like("https://e.com/about") and not is_page_like("https://e.com/a.JPG")


# --- hreflang
def test_hreflang_reciprocal_ok():
    en = page("https://e.com/en", hreflang=[("en", "https://e.com/en"), ("fr", "https://e.com/fr")])
    fr = page("https://e.com/fr", hreflang=[("fr", "https://e.com/fr"), ("en", "https://e.com/en")])
    assert validate_hreflang([en, fr]) == 2
    assert en.issues == [] and fr.issues == []


def test_hreflang_missing_return_link():
    en = page("https://e.com/en", hreflang=[("en", "https://e.com/en"), ("fr", "https://e.com/fr")])
    fr = page("https://e.com/fr", hreflang=[("fr", "https://e.com/fr")])
    validate_hreflang([en, fr])
    assert "hreflang-no-return" in en.issues and fr.issues == []
    assert "fr -> https://e.com/fr" in en.notes[0]


def test_hreflang_target_without_any_hreflang():
    en = page("https://e.com/en", hreflang=[("en", "https://e.com/en"), ("de", "https://e.com/de")])
    de = page("https://e.com/de")
    validate_hreflang([en, de])
    assert "hreflang-no-return" in en.issues


def test_hreflang_uncrawled_target_not_flagged():
    en = page("https://e.com/en", hreflang=[("en", "https://e.com/en"), ("fr", "https://e.com/fr")])
    validate_hreflang([en])
    assert en.issues == []


def test_hreflang_missing_self_invalid_code_and_conflict():
    p = page(
        "https://e.com/en",
        hreflang=[
            ("fr", "https://e.com/fr"),
            ("fr", "https://e.com/fr2"),
            ("english", "https://e.com/x"),
        ],
    )
    validate_hreflang([p])
    assert {"hreflang-missing-self", "hreflang-invalid-code", "hreflang-conflict"} <= set(p.issues)


def test_hreflang_valid_codes():
    p = page(
        "https://e.com/",
        hreflang=[
            ("x-default", "https://e.com/"),
            ("en-GB", "https://e.com/uk"),
            ("zh-Hant-TW", "https://e.com/tw"),
        ],
    )
    validate_hreflang([p])
    assert "hreflang-invalid-code" not in p.issues


# --- links / orphans
def test_orphan_detection():
    home = page("https://e.com/", links=["https://e.com/a"])
    a = page("https://e.com/a", links=["https://e.com/"])
    lonely = page("https://e.com/lonely")
    orphans, _ = analyze_links([home, a, lonely])
    assert orphans == ["https://e.com/lonely"]
    assert (home.inbound_links, a.inbound_links, lonely.inbound_links) == (1, 1, 0)


def test_self_links_do_not_count():
    a = page("https://e.com/a", links=["https://e.com/a"])
    b = page("https://e.com/b", links=["https://e.com/a"])
    orphans, _ = analyze_links([a, b])
    assert orphans == ["https://e.com/b"]


def test_linked_not_in_sitemap_excludes_assets():
    a = page("https://e.com/a", links=["https://e.com/new-page", "https://e.com/pic.png"])
    b = page("https://e.com/b", links=["https://e.com/a"])
    _, extra = analyze_links([a, b])
    assert extra == ["https://e.com/new-page"]


def test_link_to_redirect_target_counts():
    old = PageResult(
        url="https://e.com/old", final_url="https://e.com/new", final_status=200, is_html=True
    )
    other = page("https://e.com/x", links=["https://e.com/new"])
    analyze_links([old, other])
    assert old.inbound_links == 1


def test_analysis_skipped_for_single_page():
    assert analyze_links([page("https://e.com/")]) == ([], [])


def test_non_html_pages_ignored():
    a = page("https://e.com/a", links=["https://e.com/b"])
    b = page("https://e.com/b")
    c = page("https://e.com/c.pdf", html=False)
    analyze_links([a, b, c])
    assert c.inbound_links is None


# --- finalize
def test_duplicate_titles_flagged():
    pages = [
        page("https://e.com/1", title="Same"),
        page("https://e.com/2", title="same"),
        page("https://e.com/3", title="Other"),
    ]
    analysis = finalize(pages)
    assert "duplicate-title" in pages[0].issues and "duplicate-title" in pages[1].issues
    assert "duplicate-title" not in pages[2].issues and analysis.duplicate_title_groups == 1


def test_empty_and_error_page_titles_not_duplicates():
    pages = [
        page("https://e.com/1", title=""),
        page("https://e.com/2", title=""),
        page("https://e.com/3", title="X", status=404),
    ]
    finalize(pages)
    assert all("duplicate-title" not in p.issues for p in pages)


def test_robots_blocked_flag():
    rules = RobotsRules.parse("User-agent: *\nDisallow: /private/\n")
    pages = [page("https://e.com/private/x"), page("https://e.com/ok")]
    analysis = finalize(pages, rules, "https://e.com/robots.txt", "Googlebot")
    assert "blocked-by-robots" in pages[0].issues and "blocked-by-robots" not in pages[1].issues
    assert analysis.blocked_count == 1 and analysis.robots_found


def test_finalize_is_idempotent():
    pages = [
        page("https://e.com/1", title="Same", links=["https://e.com/2"]),
        page("https://e.com/2", title="Same"),
    ]
    finalize(pages)
    first = [list(p.issues) for p in pages], [list(p.notes) for p in pages]
    finalize(pages)
    assert ([list(p.issues) for p in pages], [list(p.notes) for p in pages]) == first


def test_finalize_marks_orphans():
    pages = [
        page("https://e.com/1", title="A", links=["https://e.com/2"]),
        page("https://e.com/2", title="B"),
    ]
    analysis = finalize(pages)
    assert analysis.orphans == ["https://e.com/1"] and "orphan" in pages[0].issues
