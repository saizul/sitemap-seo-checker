# sitemap-seo-checker

[![CI](https://github.com/saizul/sitemap-seo-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/sitemap-seo-checker/actions/workflows/ci.yml) ![Python](https://img.shields.io/badge/Python-ready-blue?logo=python&logoColor=white) ![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

Read an XML sitemap (plain, index or gzip), fetch every URL concurrently and get
a CSV, JSON or HTML audit of what search engines will see: status codes,
redirects, canonicals, noindex, titles, descriptions, headings, hreflang,
robots.txt blocks and orphan pages.

## Features

- Sitemaps, sitemap indexes (nested) and `.xml.gz` files; duplicates removed.
- Concurrent fetching with `ThreadPoolExecutor` (default 5 workers), optional
  per-request `--delay`, `--max-urls`, timeouts and retry with backoff.
- Per URL: first status, final status, redirect count, final URL, canonical
  (self / other / missing), meta robots, `X-Robots-Tag`, title length,
  description length, H1 count, response time.
- robots.txt parsing (wildcards, `$`, Allow/Disallow precedence, per-agent
  groups): flags sitemap URLs that are disallowed.
- hreflang validation: valid codes, self reference, conflicts and reciprocal
  (return) links between alternates.
- Internal link extraction: finds **orphan** sitemap pages (no links from other
  sitemap pages) and pages that are linked but missing from the sitemap.
- Resumable runs with a local SQLite cache (`--cache` / `--resume`).
- Progress bar on stderr, CSV (default), `--json` and `--html` outputs.

## Install

```bash
pip install .            # from a clone of this repository
# or, for development
pip install -e ".[dev]"
```

Requires Python 3.9+.

## Usage

```bash
sitemap-check https://example.com/sitemap.xml
sitemap-check https://example.com/sitemap_index.xml --workers 8 --delay 0.2 --max-urls 500
sitemap-check https://example.com/sitemap.xml --include '/blog/' --exclude '\?(page|utm_)'
sitemap-check https://example.com/sitemap.xml --json > audit.json
sitemap-check https://example.com/sitemap.xml -o audit.csv --html audit.html
sitemap-check https://example.com/sitemap.xml --cache crawl.db            # saves progress
sitemap-check https://example.com/sitemap.xml --cache crawl.db --resume   # continue later
```

| Option | Meaning |
| --- | --- |
| `--workers N` | concurrent requests (default 5) |
| `--delay S` | seconds each worker waits before a request (default 0) |
| `--max-urls N` | stop collecting after N URLs (applied after the filters below) |
| `--include REGEX` | only audit URLs matching the regex; repeat the flag to allow several patterns |
| `--exclude REGEX` | skip URLs matching the regex; repeatable, wins over `--include` |
| `--timeout S`, `--retries N` | request timeout and retries on timeout/429/5xx |
| `--user-agent TEXT` | User-Agent header (default `sitemap-seo-checker`) |
| `-o, --output CSV` | CSV path (default `sitemap-report.csv`) |
| `--json` | print JSON to stdout instead of the summary |
| `--html PATH` | also write an HTML report |
| `--cache DB`, `--resume` | SQLite cache and resume |
| `--no-robots`, `--robots-agent` | skip robots.txt, or choose the agent (default `Googlebot`) |
| `--no-progress` | hide the progress bar |
| `--fail-on-errors` | exit 1 if any error-level issue exists |

Exit codes: `0` ok, `1` errors found with `--fail-on-errors`, `2` failure
(unreadable sitemap, bad options, unwritable output), `130` interrupted.

Be considerate: keep worker counts and delays sensible for the site you audit,
and only crawl sites you own or manage.

## Sample output

Illustrative output from mocked pages:

```text
           Sitemap audit summary           
┌────────────────────────┬────────────────┐
│ URLs checked           │ 5              │
│ Clean                  │ 0              │
│ With issues            │ 5              │
│ Avg / max response     │ 6 / 6 ms       │
│ Status codes           │ 200: 4, 404: 1 │
│ robots.txt             │ found          │
│ Orphan pages           │ 3              │
│ Linked, not in sitemap │ 1              │
└────────────────────────┴────────────────┘
                                      Issues                                       
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Level   ┃ Issue             ┃ URLs ┃ Meaning                                    ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ warning │ orphan            │ 3    │ No internal links from other sitemap pages │
│ warning │ duplicate-title   │ 2    │ Title shared with another sitemap URL      │
│ error   │ blocked-by-robots │ 1    │ URL is disallowed by robots.txt            │
│ error   │ canonical-other   │ 1    │ Canonical points to a different URL        │
│ notice  │ multiple-h1       │ 1    │ More than one <h1>                         │
│ error   │ noindex           │ 1    │ noindex in meta robots or X-Robots-Tag     │
│ error   │ non-200           │ 1    │ Final status is not 200                    │
└─────────┴───────────────────┴──────┴────────────────────────────────────────────┘
                                 URLs needing attention (top 5)                                  
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Status ┃ URL                          ┃ Issues                                                ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 200    │ https://example.com/hidden   │ noindex, blocked-by-robots, orphan                    │
│ 200    │ https://example.com/dup      │ canonical-other, multiple-h1, duplicate-title, orphan │
│ 404    │ https://example.com/old-page │ non-200                                               │
│ 200    │ https://example.com/         │ orphan                                                │
│ 200    │ https://example.com/about    │ duplicate-title                                       │
└────────┴──────────────────────────────┴───────────────────────────────────────────────────────┘
CSV written to sitemap-report.csv
```

## Issue codes

| Code | Level | Meaning |
| --- | --- | --- |
| `fetch-error` | error | URL could not be fetched |
| `non-200` | error | final status is not 200 |
| `noindex` | error | noindex in meta robots or `X-Robots-Tag` |
| `blocked-by-robots` | error | disallowed by robots.txt |
| `canonical-other` | error | canonical points to a different URL |
| `redirect` | warning | URL redirects |
| `duplicate-title` | warning | title shared with another sitemap URL |
| `missing-title`, `missing-h1` | warning | no title / no H1 |
| `orphan` | warning | no internal links from other sitemap pages |
| `hreflang-no-return` | warning | an alternate does not link back |
| `hreflang-missing-self` | warning | hreflang set lacks a self reference |
| `hreflang-invalid-code` | warning | invalid language code |
| `hreflang-conflict` | warning | same code, different URLs |
| `canonical-missing` | notice | no canonical link |
| `multiple-h1` | notice | more than one H1 |
| `title-too-long` | notice | title over 60 characters |
| `missing-description` | notice | no meta description |
| `description-too-long` | notice | description over 160 characters |

## Notes and limits

- Response time is measured until headers arrive, including redirects.
- Only the first 2 MB of an HTML page is parsed; non-HTML URLs are not parsed.
- Orphan detection only knows links found on crawled sitemap pages. With
  `--max-urls`, or when navigation is injected by JavaScript, results can contain
  false positives. Pages are not rendered in a browser.
- A missing or unreachable robots.txt is treated as "everything allowed".
- `--resume` reuses stored results for the same sitemap URL and retries URLs that
  previously failed. Without `--resume` the stored run is replaced.
- Cross-page checks (duplicates, robots, hreflang, orphans) are recomputed on
  every run, so cached results never go stale on those.
- Sitemaps containing XML entity declarations are rejected.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

Tests use mocked HTTP responses and fixture files only; they never touch the network.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE). Author: Saizul Amin, https://saizul.com
