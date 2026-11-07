import json

import pytest
from conftest import fixture_bytes
from test_report_cli import SITEMAP, run, site
from test_sitemap import fake_fetch

from sitemap_seo_checker.cli import main
from sitemap_seo_checker.sitemap import collect_urls, compile_patterns, url_allowed

S = "https://example.com/s.xml"
MAPPING = {S: fixture_bytes("sitemap_urlset.xml")}  # /, /about, /contact (+ a duplicate /about)


def urls(**kw):
    return collect_urls(fake_fetch(MAPPING), S, **kw)


def test_url_allowed_logic():
    inc = compile_patterns([r"/blog/"])
    exc = compile_patterns([r"\?page="])
    assert url_allowed("https://e.com/blog/a")
    assert url_allowed("https://e.com/blog/a", inc, exc)
    assert not url_allowed("https://e.com/shop/a", inc, exc)
    assert not url_allowed("https://e.com/blog/a?page=2", inc, exc)  # exclude wins


def test_include_keeps_only_matches():
    col = urls(include=compile_patterns([r"/about$", r"/contact$"]))
    assert col.urls == ["https://example.com/about", "https://example.com/contact"]
    assert col.filtered == 1


def test_exclude_drops_matches_and_counts_once():
    col = urls(exclude=compile_patterns([r"/about"]))  # appears twice in the sitemap
    assert col.urls == ["https://example.com/", "https://example.com/contact"]
    assert col.filtered == 1


def test_exclude_beats_include():
    col = urls(include=compile_patterns([r"example\.com"]), exclude=compile_patterns([r"contact"]))
    assert "https://example.com/contact" not in col.urls


def test_filters_apply_before_max_urls():
    col = urls(exclude=compile_patterns([r"example\.com/$"]), max_urls=2)
    assert col.urls == ["https://example.com/about", "https://example.com/contact"]
    assert not col.truncated


def test_compile_patterns_rejects_bad_regex():
    with pytest.raises(ValueError, match="invalid regular expression"):
        compile_patterns(["("])


def test_cli_include_exclude(mock, tmp_path, capsys):
    site(mock, robots=False)
    run(["--json", "--include", "post-", "--exclude", "post-2"], tmp_path)
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["total_urls"] == 1


def test_cli_repeated_include(mock, tmp_path, capsys):
    site(mock, robots=False)
    run(["--json", "--include", "post-1", "--include", r"\.com/$"], tmp_path)
    assert json.loads(capsys.readouterr().out)["summary"]["total_urls"] == 2


def test_cli_invalid_regex(capsys):
    assert main([SITEMAP, "--include", "("]) == 2
    assert "invalid regular expression" in capsys.readouterr().err


def test_cli_filters_remove_everything(mock, tmp_path, capsys):
    site(mock, robots=False)
    assert run(["--include", "nothing-matches"], tmp_path) == 2
    assert "removed every URL" in capsys.readouterr().err
