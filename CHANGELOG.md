# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `--compare JSON`: compare the audit with a previous `--json` report. Shows new and fixed issues per
  URL, final status changes and URLs added to or removed from the sitemap, in the console summary, the
  HTML report and under `comparison` in the JSON output.
- `--fail-on-new-errors`: with `--compare`, exit 1 only when an error-level issue appeared since the
  previous report.
