# Contributing

Thanks for helping improve sitemap-seo-checker.

## Ground rules

- The tool only reads pages that are listed in a sitemap you point it at. Keep
  the default request rate polite and never add features that submit forms,
  bypass robots rules silently, or hide the User-Agent.
- Tests must not use the network. Mock HTTP with the `responses` library and
  keep sample documents in `tests/fixtures/`.
- New behaviour needs tests; new issue codes need an entry in
  `models.ISSUES` and the README table.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```

## Layout

| Module | Responsibility |
| --- | --- |
| `sitemap.py` | parse sitemaps, indexes and gzip files |
| `robots.py` | robots.txt parser with wildcard support |
| `fetch.py` | HTTP with retries, delay and thread-local sessions |
| `analyzer.py` | turn one response into a `PageResult` |
| `hreflang.py`, `links.py`, `postprocess.py` | cross-page checks |
| `cache.py` | SQLite cache used for resumable runs |
| `crawler.py` | concurrent crawl with progress callbacks |
| `sitemap_lint.py` | sitemap protocol checks (limits, `<loc>`, `<lastmod>`, host and scope) |
| `report.py` | CSV, JSON, HTML and console output |
| `compare.py` | diff against a previous JSON report (`--compare`) |

## Pull requests

Keep changes focused and make sure `ruff check .`, `ruff format --check .` and `pytest` pass on
Python 3.10 to 3.13.
