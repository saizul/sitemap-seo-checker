import gzip

import pytest
import responses
from conftest import fixture_bytes

from sitemap_seo_checker.fetch import FetchError
from sitemap_seo_checker.sitemap import SitemapError, collect_urls, decompress, parse_sitemap


def test_parse_urlset_with_namespaces_and_whitespace():
    kind, locs = parse_sitemap(fixture_bytes("sitemap_urlset.xml"))
    assert kind == "urlset"
    assert locs[2] == "https://example.com/contact"
    assert len(locs) == 4


def test_parse_index():
    kind, locs = parse_sitemap(fixture_bytes("sitemap_index.xml"))
    assert kind == "index" and len(locs) == 2


def test_parse_gzip():
    kind, locs = parse_sitemap(gzip.compress(fixture_bytes("sitemap_posts.xml")))
    assert kind == "urlset" and locs[0].endswith("post-1")


def test_decompress_plain_passthrough():
    assert decompress(b"<a/>") == b"<a/>"


def test_invalid_gzip():
    with pytest.raises(SitemapError):
        decompress(b"\x1f\x8bnot really gzip")


def test_invalid_xml():
    with pytest.raises(SitemapError):
        parse_sitemap(b"<urlset><url>")


def test_wrong_root():
    with pytest.raises(SitemapError, match="not a sitemap"):
        parse_sitemap(b"<html><body/></html>")


def test_entities_rejected():
    xml = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><urlset></urlset>'
    with pytest.raises(SitemapError, match="entity"):
        parse_sitemap(xml)


def test_empty_loc_ignored():
    kind, locs = parse_sitemap(
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc> </loc></url></urlset>'
    )
    assert locs == []


def fake_fetch(mapping):
    def fetch(url):
        if url not in mapping:
            raise FetchError(f"{url}: HTTP 404")
        return mapping[url]

    return fetch


def test_collect_dedupes_in_order():
    col = collect_urls(
        fake_fetch({"https://example.com/s.xml": fixture_bytes("sitemap_urlset.xml")}),
        "https://example.com/s.xml",
    )
    assert col.urls == [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/contact",
    ]


def test_collect_index_with_gzip_child():
    mapping = {
        "https://example.com/index.xml": fixture_bytes("sitemap_index.xml"),
        "https://example.com/sitemap-posts.xml": fixture_bytes("sitemap_posts.xml"),
        "https://example.com/sitemap-pages.xml.gz": gzip.compress(
            fixture_bytes("sitemap_pages.xml")
        ),
    }
    col = collect_urls(fake_fetch(mapping), "https://example.com/index.xml")
    assert col.urls == [
        "https://example.com/post-1",
        "https://example.com/post-2",
        "https://example.com/",
    ]
    assert len(col.sitemaps) == 3


def test_collect_max_urls_truncates():
    mapping = {"https://e.com/s.xml": fixture_bytes("sitemap_urlset.xml")}
    col = collect_urls(fake_fetch(mapping), "https://e.com/s.xml", max_urls=2)
    assert len(col.urls) == 2 and col.truncated


def test_collect_max_urls_stops_index_walk():
    calls = []

    def fetch(url):
        calls.append(url)
        return {
            "https://example.com/index.xml": fixture_bytes("sitemap_index.xml"),
            "https://example.com/sitemap-posts.xml": fixture_bytes("sitemap_posts.xml"),
        }[url]

    col = collect_urls(fetch, "https://example.com/index.xml", max_urls=2)
    assert len(col.urls) == 2 and "https://example.com/sitemap-pages.xml.gz" not in calls


def test_child_failure_recorded_not_fatal():
    mapping = {
        "https://example.com/index.xml": fixture_bytes("sitemap_index.xml"),
        "https://example.com/sitemap-posts.xml": fixture_bytes("sitemap_posts.xml"),
    }
    col = collect_urls(fake_fetch(mapping), "https://example.com/index.xml")
    assert len(col.urls) == 2 and len(col.errors) == 1


def test_root_failure_raises():
    with pytest.raises(SitemapError):
        collect_urls(fake_fetch({}), "https://example.com/missing.xml")


def test_cycle_protection():
    xml = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://e.com/a.xml</loc></sitemap></sitemapindex>'
    col = collect_urls(fake_fetch({"https://e.com/a.xml": xml}), "https://e.com/a.xml")
    assert col.urls == [] and len(col.sitemaps) == 1


def test_get_bytes_over_http(mock, fetcher):
    mock.add(
        responses.GET,
        "https://example.com/s.xml",
        body=gzip.compress(b"<urlset/>"),
        content_type="application/gzip",
    )
    assert decompress(fetcher.get_bytes("https://example.com/s.xml")) == b"<urlset/>"


def test_get_bytes_http_error(mock, fetcher):
    mock.add(responses.GET, "https://example.com/s.xml", status=404)
    with pytest.raises(FetchError, match="404"):
        fetcher.get_bytes("https://example.com/s.xml")


def test_get_bytes_size_cap(mock, fetcher):
    mock.add(responses.GET, "https://example.com/s.xml", body=b"x" * 5000)
    with pytest.raises(FetchError, match="larger"):
        fetcher.get_bytes("https://example.com/s.xml", max_bytes=1000)
