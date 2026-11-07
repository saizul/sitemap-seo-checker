"""robots.txt parsing with wildcard and longest-match support."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern, Tuple
from urllib.parse import urlparse

from .fetch import Fetcher


@dataclass
class Rule:
    """One Allow/Disallow line."""

    allow: bool
    pattern: str
    regex: Pattern[str]


def _compile(pattern: str) -> Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "^" + re.escape(body).replace(r"\*", ".*") + ("$" if anchored else "")
    return re.compile(regex)


@dataclass
class RobotsRules:
    """Parsed robots.txt."""

    groups: Dict[str, List[Rule]] = field(default_factory=dict)
    sitemaps: List[str] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        """Parse robots.txt content."""
        rules = cls()
        agents: List[str] = []
        last_was_rule = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            name, value = (part.strip() for part in line.split(":", 1))
            name = name.lower()
            if name == "user-agent":
                if last_was_rule:
                    agents = []
                agents.append(value.lower())
                rules.groups.setdefault(value.lower(), [])
                last_was_rule = False
            elif name in ("allow", "disallow"):
                last_was_rule = True
                if value:
                    rule = Rule(name == "allow", value, _compile(value))
                    for agent in agents:
                        rules.groups[agent].append(rule)
            elif name == "sitemap" and value:
                rules.sitemaps.append(value)
        return rules

    def _rules_for(self, agent: str) -> List[Rule]:
        agent = agent.lower()
        matches = [a for a in self.groups if a != "*" and a in agent]
        if matches:
            return self.groups[max(matches, key=len)]
        return self.groups.get("*", [])

    def is_allowed(self, agent: str, url_or_path: str) -> bool:
        """Whether ``agent`` may fetch the URL (or path with optional query)."""
        parts = urlparse(url_or_path)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        best: Optional[Tuple[int, bool]] = None
        for rule in self._rules_for(agent):
            if rule.regex.match(path):
                candidate = (len(rule.pattern), rule.allow)
                if best is None or candidate > best:
                    best = candidate
        return True if best is None else best[1]


def robots_url_for(url: str) -> str:
    """robots.txt location for the host of ``url``."""
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def load_robots(fetcher: Fetcher, url: str) -> Tuple[Optional[RobotsRules], str]:
    """Fetch and parse robots.txt. Returns ``(rules or None, robots_url)``.

    A missing or unreachable robots.txt means "everything allowed" (None).
    """
    robots_url = robots_url_for(url)
    try:
        data = fetcher.get_bytes(robots_url, max_bytes=1024 * 1024)
    except Exception:
        return None, robots_url
    return RobotsRules.parse(data.decode("utf-8", "replace")), robots_url
