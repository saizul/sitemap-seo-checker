import pytest
import responses
from conftest import fixture_text

from sitemap_seo_checker.robots import RobotsRules, load_robots, robots_url_for

RULES = RobotsRules.parse(fixture_text("robots.txt"))


def test_sitemap_directive_parsed():
    assert RULES.sitemaps == ["https://example.com/sitemap.xml"]


def test_star_group_disallow():
    assert not RULES.is_allowed("OtherBot", "https://example.com/private/page")
    assert RULES.is_allowed("OtherBot", "https://example.com/open")


def test_allow_overrides_longer_match():
    assert RULES.is_allowed("OtherBot", "/private/public-note")


def test_wildcard_and_end_anchor():
    assert not RULES.is_allowed("OtherBot", "/files/doc.pdf")
    assert RULES.is_allowed("OtherBot", "/files/doc.pdf.html")


def test_query_matching():
    assert not RULES.is_allowed("OtherBot", "/search?q=x")
    assert RULES.is_allowed("OtherBot", "/search")


def test_specific_group_wins_over_star():
    assert RULES.is_allowed("Googlebot", "/private/page")  # star rules ignored for Googlebot
    assert not RULES.is_allowed("Googlebot", "/nogoogle/x")


def test_shared_group_for_multiple_agents():
    assert not RULES.is_allowed("bingbot/2.0", "/nogoogle/x")


def test_tie_goes_to_allow():
    rules = RobotsRules.parse("User-agent: *\nDisallow: /a\nAllow: /a\n")
    assert rules.is_allowed("x", "/a")


def test_empty_disallow_allows_all():
    rules = RobotsRules.parse("User-agent: *\nDisallow:\n")
    assert rules.is_allowed("x", "/anything")


def test_no_matching_group_allows():
    rules = RobotsRules.parse("User-agent: special\nDisallow: /\n")
    assert rules.is_allowed("other", "/x")
    assert not rules.is_allowed("special-bot", "/x")


def test_comments_and_junk_ignored():
    rules = RobotsRules.parse("garbage\nUser-agent: * # all\nDisallow: /x # no\n")
    assert not rules.is_allowed("a", "/x")


def test_disallow_root():
    rules = RobotsRules.parse("User-agent: *\nDisallow: /\n")
    assert not rules.is_allowed("a", "https://e.com/anything")


@pytest.mark.parametrize("url", ["https://e.com/a/b?c=1", "https://e.com"])
def test_robots_url_for(url):
    assert robots_url_for(url) == "https://e.com/robots.txt"


def test_load_robots_ok(mock, fetcher):
    mock.add(
        responses.GET,
        "https://example.com/robots.txt",
        body=fixture_text("robots.txt"),
        content_type="text/plain",
    )
    rules, url = load_robots(fetcher, "https://example.com/sitemap.xml")
    assert rules is not None and url == "https://example.com/robots.txt"


def test_load_robots_missing(mock, fetcher):
    mock.add(responses.GET, "https://example.com/robots.txt", status=404)
    assert load_robots(fetcher, "https://example.com/sitemap.xml")[0] is None
