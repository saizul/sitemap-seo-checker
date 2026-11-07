from pathlib import Path

import pytest
import responses

from sitemap_seo_checker.fetch import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def add_page(mock, url, body="", status=200, headers=None, content_type="text/html"):
    mock.add(
        responses.GET,
        url,
        body=body,
        status=status,
        headers=headers or {},
        content_type=content_type,
    )


@pytest.fixture
def fetcher():
    return Fetcher(delay=0, retries=0, sleep=lambda s: None)


@pytest.fixture
def mock():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps
