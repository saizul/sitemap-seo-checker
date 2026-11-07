"""SQLite cache that makes crawls resumable."""

from __future__ import annotations

import json
import sqlite3
from types import TracebackType
from typing import Dict, Optional, Type

from .models import PageResult


class Cache:
    """Stores finished :class:`PageResult` objects per run key (the sitemap URL).

    All access happens from the main thread; results are committed one by one so
    an interrupted crawl keeps everything fetched so far.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS pages ("
            "run TEXT NOT NULL, url TEXT NOT NULL, data TEXT NOT NULL, "
            "PRIMARY KEY (run, url))"
        )
        self._db.commit()

    def load(self, run: str) -> Dict[str, PageResult]:
        """All stored results for ``run``, keyed by URL."""
        rows = self._db.execute("SELECT url, data FROM pages WHERE run = ?", (run,)).fetchall()
        out: Dict[str, PageResult] = {}
        for url, data in rows:
            try:
                page = PageResult.from_dict(json.loads(data))
            except (ValueError, TypeError):
                continue  # ignore a corrupt row; it will be fetched again
            page.from_cache = True
            out[url] = page
        return out

    def save(self, run: str, page: PageResult) -> None:
        """Insert or replace one result."""
        payload = json.dumps(page.to_dict(full=True))
        self._db.execute(
            "INSERT OR REPLACE INTO pages (run, url, data) VALUES (?, ?, ?)",
            (run, page.url, payload),
        )
        self._db.commit()

    def clear(self, run: str) -> None:
        """Forget everything stored for ``run``."""
        self._db.execute("DELETE FROM pages WHERE run = ?", (run,))
        self._db.commit()

    def count(self, run: str) -> int:
        """Number of stored results for ``run``."""
        row = self._db.execute("SELECT COUNT(*) FROM pages WHERE run = ?", (run,)).fetchone()
        return int(row[0])

    def close(self) -> None:
        """Close the database."""
        self._db.close()

    def __enter__(self) -> Cache:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()
