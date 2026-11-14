# sitemap-seo-checker

[![CI](https://github.com/saizul/sitemap-seo-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/sitemap-seo-checker/actions/workflows/ci.yml) ![Python](https://img.shields.io/badge/Python-ready-blue?logo=python&logoColor=white) ![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

Read an XML sitemap (plain, index or gzip), fetch every URL concurrently and get
a CSV, JSON or HTML audit of what search engines will see: status codes,
redirects, canonicals, noindex, titles, descriptions, headings, hreflang,
robots.txt blocks and orphan pages.

## Features

- Sitemaps, sitemap indexes (nested) and `.xml.gz` files; duplicates removed.
- Sitemap file checks against the sitemaps.org protocol: 50,000 entry and 50 MB
  limits, invalid or relative `<loc>`, malformed or future `<lastmod>`, URLs on
  another host or outside the sitemap's directory, duplicates and nested indexes
  (see [Sitemap file checks](#sitemap-file-checks)).
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
- Compare a run with a previous JSON report (`--compare`) to see new and fixed
  issues, status changes and added / removed URLs, and fail CI on regressions only.
- Progress bar on stderr, CSV (default), `--json` and `--html` outputs.

## Install

```bash
pip install .            # from a clone of this repository
# or, for development
pip install -e ".[dev]"
```

Requires Python 3.10+.

## Usage

```bash
sitemap-check https://example.com/sitemap.xml
sitemap-check https://example.com/sitemap_index.xml --workers 8 --delay 0.2 --max-urls 500
sitemap-check https://example.com/sitemap.xml --include '/blog/' --exclude '\?(page|utm_)'
sitemap-check https://example.com/sitemap.xml --json > audit.json
sitemap-check https://example.com/sitemap.xml -o audit.csv --html audit.html
sitemap-check https://example.com/sitemap.xml --cache crawl.db            # saves progress
sitemap-check https://example.com/sitemap.xml --cache crawl.db --resume   # continue later
sitemap-check https://example.com/sitemap.xml --compare last-week.json     # what changed?
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
| `--soft-404-min-words N` | also flag 200 pages with fewer than N visible words as `soft-404` (default 0 = off) |
| `--no-sitemap-checks` | skip the sitemap file checks (limits, `<loc>`, `<lastmod>`, host and scope) |
| `--no-robots`, `--robots-agent` | skip robots.txt, or choose the agent (default `Googlebot`) |
| `--no-progress` | hide the progress bar |
| `--compare JSON` | compare with a previous `--json` report: new / fixed issues, status changes, added / removed URLs |
| `--fail-on-new-errors` | with `--compare`: exit 1 if an error-level issue appeared since the previous report |
| `--fail-on-errors` | exit 1 if any error-level page issue or sitemap file finding exists |

Numeric options are validated up front: `--workers` and `--max-urls` must be at least 1, `--timeout` must be greater than 0, and `--delay` / `--retries` must not be negative.

Exit codes: `0` ok, `1` errors found with `--fail-on-errors` (or new errors with
`--fail-on-new-errors`), `2` failure
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

## Comparing with a previous run

Keep the JSON report of an audit and pass it to the next one with `--compare`
to see what changed instead of re-reading the whole report:

```bash
sitemap-check https://example.com/sitemap.xml --json > monday.json
# ... a week later
sitemap-check https://example.com/sitemap.xml --compare monday.json
sitemap-check https://example.com/sitemap.xml --compare monday.json --json > today.json
```

```text
        Changes since the previous report        
┌───────────────────┬───────────────────────────┐
│ Previous report   │ 2026-01-05T08:00:00+00:00 │
│ URLs before / now │ 4 / 4                     │
│ Added URLs        │ 1                         │
│ Removed URLs      │ 1                         │
│ URLs with changes │ 2                         │
│ New issues        │ 2                         │
│ New errors        │ 1                         │
│ Fixed issues      │ 1                         │
└───────────────────┴───────────────────────────┘
           Issue changes            
┏━━━━━━━━━┳━━━━━━━━━━┳━━━━━┳━━━━━━━┓
┃ Level   ┃ Issue    ┃ New ┃ Fixed ┃
┡━━━━━━━━━╇━━━━━━━━━━╇━━━━━╇━━━━━━━┩
│ error   │ non-200  │ 1   │ 0     │
│ warning │ orphan   │ 1   │ 0     │
│ warning │ redirect │ 0   │ 1     │
└─────────┴──────────┴─────┴───────┘
                       Changed URLs (top 2 of 2)                        
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Status     ┃ URL                         ┃ New issues ┃ Fixed issues ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 200 -> 404 │ https://example.com/pricing │ non-200    │ -            │
│ 200        │ https://example.com/about   │ -          │ redirect     │
└────────────┴─────────────────────────────┴────────────┴──────────────┘
Added URLs: https://example.com/blog/launch
Removed URLs: https://example.com/old-page
```

- The comparison is printed after the summary, added to the HTML report
  (`--html`) and stored under `comparison` in the JSON output.
- Issues on URLs that are new in this run count as new issues. A URL that left
  the sitemap is listed as removed; its old issues are not counted as fixed.
- `--fail-on-new-errors` exits with `1` only when an error-level issue appeared
  since the previous report, so a scheduled job can alert on regressions while
  known, accepted problems stay quiet. `--fail-on-errors` still works as before.
- Compare runs made with the same `--include`, `--exclude` and `--max-urls`
  options, otherwise URLs show up as added or removed. Do not redirect `--json`
  output into the file you are comparing with: the shell empties it first.

## Issue codes

| Code | Level | Meaning |
| --- | --- | --- |
| `fetch-error` | error | URL could not be fetched |
| `non-200` | error | final status is not 200 |
| `noindex` | error | noindex in meta robots or `X-Robots-Tag` |
| `blocked-by-robots` | error | disallowed by robots.txt |
| `canonical-other` | error | canonical points to a different URL |
| `soft-404` | warning | 200 page that says "not found" in its title, H1 or short body (or has too little text with `--soft-404-min-words`) |
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

## Sitemap file checks

Every sitemap file that is read (the root, and each child of an index) is also
checked against the [sitemaps.org protocol](https://www.sitemaps.org/protocol.html).
Findings are grouped per file and code, with a count and up to five example URLs.
They appear in a "Sitemap file checks" table in the console and HTML reports, and
under `analysis.sitemap_findings` in the JSON output:

```json
{"sitemap": "https://example.com/post-sitemap.xml", "code": "invalid-lastmod",
 "level": "warning", "count": 2, "examples": ["https://example.com/a (31/03/2026)"], "detail": ""}
```

| Code | Level | Meaning |
| --- | --- | --- |
| `too-many-entries` | error | more than 50,000 `<url>` or `<sitemap>` entries in one file |
| `too-large` | error | larger than 50 MB (52,428,800 bytes) after decompression |
| `invalid-loc` | error | `<loc>` is not an absolute `http(s)` URL (relative, other scheme, spaces) |
| `loc-too-long` | warning | `<loc>` is 2,048 characters or longer |
| `invalid-lastmod` | warning | `<lastmod>` is not a W3C datetime (`2026-03-31`, `2026-03-31T10:15:30+06:00`; a time needs a zone) |
| `future-lastmod` | warning | `<lastmod>` more than one day in the future |
| `off-host` | warning | URL on a different host than the sitemap (`www.` counts as a different host); only valid with cross-site verification |
| `nested-index` | warning | a sitemap index lists another sitemap index |
| `duplicate-loc` | notice | URL already listed earlier in the sitemap tree (it is audited once) |
| `out-of-scope` | notice | URL outside the directory of the sitemap file, e.g. `/shop/` in `/blog/sitemap.xml` |
| `empty-sitemap` | notice | a `<urlset>` file without URLs |

Error-level findings make `--fail-on-errors` exit 1. Use `--no-sitemap-checks` to
turn the checks off.

## Notes and limits

- Response time is measured until headers arrive, including redirects.
- Only the first 2 MB of an HTML page is parsed; non-HTML URLs are not parsed.
- Orphan detection only knows links found on crawled sitemap pages. With
  `--max-urls`, or when navigation is injected by JavaScript, results can contain
  false positives. Pages are not rendered in a browser.
- `soft-404` looks for wording such as "not found", "404" or "does not exist" in the `<title>` and first `<h1>`, and in the body only when the page has 250 words or fewer. The thin-content check is opt-in because JavaScript-rendered pages look empty without a browser. The reason is stored in the row's notes (JSON output). Cached results are not re-evaluated, so run without `--resume` after changing the threshold.
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
ruff format --check .
pytest
```

Tests use mocked HTTP responses and fixture files only; they never touch the network.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE). Author: Saizul Amin, https://saizul.com

## Run with Docker

A multi-arch image (amd64, arm64) is published to GitHub Container Registry on every change to `main`:

```bash
docker run --rm ghcr.io/saizul/sitemap-seo-checker:latest https://example.com
# write reports to the current folder
docker run --rm -v "$PWD:/work" ghcr.io/saizul/sitemap-seo-checker:latest --help
```
