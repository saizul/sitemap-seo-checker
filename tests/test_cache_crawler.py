from conftest import add_page

from sitemap_seo_checker.cache import Cache
from sitemap_seo_checker.crawler import crawl
from sitemap_seo_checker.models import PageResult

URLS = [f"https://example.com/p{i}" for i in range(6)]


def mock_site(mock):
    for u in URLS:
        add_page(mock, u, f"<title>T {u[-1]}</title><h1>x</h1>")


def test_cache_save_load_roundtrip(tmp_path):
    with Cache(str(tmp_path / "c.db")) as cache:
        cache.save("run", PageResult(url="u1", title="T", internal_links=["a"]))
        loaded = cache.load("run")
        assert loaded["u1"].title == "T" and loaded["u1"].from_cache
        assert loaded["u1"].internal_links == ["a"]
        assert cache.count("run") == 1 and cache.load("other") == {}


def test_cache_replace_and_clear(tmp_path):
    with Cache(str(tmp_path / "c.db")) as cache:
        cache.save("r", PageResult(url="u", title="old"))
        cache.save("r", PageResult(url="u", title="new"))
        assert cache.load("r")["u"].title == "new"
        cache.clear("r")
        assert cache.count("r") == 0


def test_cache_persists_between_connections(tmp_path):
    path = str(tmp_path / "c.db")
    with Cache(path) as cache:
        cache.save("r", PageResult(url="u"))
    with Cache(path) as cache:
        assert "u" in cache.load("r")


def test_cache_skips_corrupt_rows(tmp_path):
    cache = Cache(str(tmp_path / "c.db"))
    cache._db.execute("INSERT INTO pages VALUES ('r', 'bad', 'not json')")
    cache.save("r", PageResult(url="good"))
    assert list(cache.load("r")) == ["good"]
    cache.close()


def test_crawl_returns_input_order(mock, fetcher):
    mock_site(mock)
    results = crawl(URLS, fetcher, workers=4)
    assert [r.url for r in results] == URLS and all(r.final_status == 200 for r in results)


def test_crawl_single_worker(mock, fetcher):
    mock_site(mock)
    assert len(crawl(URLS, fetcher, workers=1)) == 6


def test_crawl_progress_callback(mock, fetcher):
    mock_site(mock)
    seen = []
    crawl(URLS, fetcher, workers=3, on_progress=lambda d, t, p: seen.append((d, t)))
    assert sorted(seen) == [(i, 6) for i in range(1, 7)]


def test_crawl_survives_failures(mock, fetcher):
    add_page(mock, URLS[0], "<title>ok</title>")
    results = crawl(URLS[:2], fetcher, workers=2)
    assert results[0].final_status == 200 and results[1].error


def test_crawl_duplicate_urls_fetched_once(mock, fetcher):
    add_page(mock, URLS[0], "<title>ok</title>")
    results = crawl([URLS[0], URLS[0]], fetcher)
    assert len(mock.calls) == 1 and len(results) == 2


def test_crawl_writes_cache(mock, fetcher, tmp_path):
    mock_site(mock)
    with Cache(str(tmp_path / "c.db")) as cache:
        crawl(URLS, fetcher, cache=cache, run_key="s")
        assert cache.count("s") == 6


def test_resume_skips_cached_urls(mock, fetcher, tmp_path):
    mock_site(mock)
    with Cache(str(tmp_path / "c.db")) as cache:
        crawl(URLS[:4], fetcher, cache=cache, run_key="s")
        mock.calls.reset()
        seen = []
        results = crawl(
            URLS,
            fetcher,
            cache=cache,
            run_key="s",
            resume=True,
            on_progress=lambda d, t, p: seen.append(d),
        )
        assert len(mock.calls) == 2  # only the two new URLs
        assert [r.url for r in results] == URLS
        assert [r.from_cache for r in results] == [True] * 4 + [False] * 2
        assert max(seen) == 6


def test_resume_retries_errors(mock, fetcher, tmp_path):
    with Cache(str(tmp_path / "c.db")) as cache:
        crawl(URLS[:1], fetcher, cache=cache, run_key="s")  # fails: nothing mocked
        assert cache.load("s")[URLS[0]].error
        add_page(mock, URLS[0], "<title>now fine</title>")
        results = crawl(URLS[:1], fetcher, cache=cache, run_key="s", resume=True)
        assert results[0].final_status == 200 and not results[0].error


def test_no_resume_clears_cache(mock, fetcher, tmp_path):
    mock_site(mock)
    with Cache(str(tmp_path / "c.db")) as cache:
        crawl(URLS[:3], fetcher, cache=cache, run_key="s")
        crawl(URLS[3:4], fetcher, cache=cache, run_key="s")
        assert list(cache.load("s")) == [URLS[3]]


def test_interrupt_keeps_completed_results(mock, fetcher, tmp_path):
    mock_site(mock)
    with Cache(str(tmp_path / "c.db")) as cache:
        count = []

        def boom(done, total, page):
            count.append(done)
            if done == 2:
                raise KeyboardInterrupt

        try:
            crawl(URLS, fetcher, workers=1, cache=cache, run_key="s", on_progress=boom)
        except KeyboardInterrupt:
            pass
        assert cache.count("s") >= 2
