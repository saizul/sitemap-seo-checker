"""Concurrent crawling with optional SQLite resume."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from .analyzer import analyze
from .cache import Cache
from .fetch import Fetcher
from .models import PageResult

ProgressCallback = Callable[[int, int, PageResult], None]


def crawl(
    urls: List[str],
    fetcher: Fetcher,
    workers: int = 5,
    cache: Optional[Cache] = None,
    run_key: str = "",
    resume: bool = False,
    on_progress: Optional[ProgressCallback] = None,
) -> List[PageResult]:
    """Analyze every URL and return results in input order.

    With ``cache`` and ``resume`` previously completed URLs are reused (results
    that ended in a fetch error are retried). Without ``resume`` the stored run
    is cleared first. ``on_progress(done, total, result)`` is called from the
    calling thread after every finished URL, cached ones included.
    """
    done: Dict[str, PageResult] = {}
    if cache is not None:
        if resume:
            wanted = set(urls)
            done = {u: p for u, p in cache.load(run_key).items() if not p.error and u in wanted}
        else:
            cache.clear(run_key)
    total = len(urls)
    finished = 0
    for url in urls:
        if url in done and on_progress:
            finished += 1
            on_progress(finished, total, done[url])
    todo = [u for u in dict.fromkeys(urls) if u not in done]
    executor = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures = {executor.submit(analyze, u, fetcher): u for u in todo}
        for future in as_completed(futures):
            page = future.result()
            done[page.url] = page
            if cache is not None:
                cache.save(run_key, page)
            finished += 1
            if on_progress:
                on_progress(finished, total, page)
    except BaseException:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
    return [done[u] for u in urls if u in done]
