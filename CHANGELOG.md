# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Sitemap file checks (`sitemap_lint.py`): every sitemap file read is checked against the
  sitemaps.org protocol for the 50,000 entry and 50 MB limits, invalid or relative `<loc>`,
  `<loc>` of 2,048+ characters, malformed (non W3C datetime) and future `<lastmod>`, URLs on
  another host or outside the sitemap's directory, duplicate URLs and nested sitemap indexes.
  Findings are grouped per file with counts and examples and shown in the console summary, the
  HTML report and under `analysis.sitemap_findings` in the JSON output.
- `--no-sitemap-checks` to turn the sitemap file checks off.
- `parse_entries()` returns each entry's `<loc>` and `<lastmod>` plus the uncompressed size.
- `--compare JSON`: compare the audit with a previous `--json` report. Shows new and fixed issues per
  URL, final status changes and URLs added to or removed from the sitemap, in the console summary, the
  HTML report and under `comparison` in the JSON output.
- `--fail-on-new-errors`: with `--compare`, exit 1 only when an error-level issue appeared since the
  previous report.

### Changed
- `--fail-on-errors` also exits 1 for error-level sitemap file findings (`too-many-entries`,
  `too-large`, `invalid-loc`).
- Python 3.10 or newer is required (3.9 dropped); CI also runs on 3.13.
