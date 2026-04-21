import pytest

from src.config.loader import get_secrets
from src.search.brave import BraveSearch, _freshness


def test_freshness_mapping():
    assert _freshness(1) == "pd"
    assert _freshness(7) == "pw"
    assert _freshness(30) == "pm"
    assert _freshness(400) == "py"


def test_brave_requires_api_key():
    with pytest.raises(ValueError):
        BraveSearch("")


def test_parse_news_response_shape():
    data = {
        "results": [
            {
                "title": "Sample",
                "url": "https://example.com/a",
                "description": "Snippet",
                "page_age": "2026-04-18T10:00:00",
                "meta_url": {"hostname": "example.com"},
                "age": "2 days ago",
            },
            {"title": "No URL", "url": ""},  # dropped
        ]
    }
    out = BraveSearch._parse(data, kind="news", lang="en")
    assert len(out) == 1
    assert out[0].url == "https://example.com/a"
    assert out[0].source == "example.com"
    assert out[0].published_at is not None
    assert out[0].metadata == {"kind": "news", "age": "2 days ago"}


def test_parse_web_response_shape():
    data = {
        "web": {
            "results": [
                {
                    "title": "Web result",
                    "url": "https://example.com/b",
                    "description": "Web snippet",
                    "meta_url": {"hostname": "example.com"},
                }
            ]
        }
    }
    out = BraveSearch._parse(data, kind="web", lang="en")
    assert len(out) == 1
    assert out[0].metadata["kind"] == "web"


@pytest.mark.live
def test_brave_live_news_smoke():
    """Live API smoke test — requires BRAVE_SEARCH_API_KEY in .env.

    Run with: pytest -m live
    """
    secrets = get_secrets()
    if not secrets.brave_search_api_key:
        pytest.skip("BRAVE_SEARCH_API_KEY not configured")
    with BraveSearch(secrets.brave_search_api_key) as client:
        articles = client.search("NVIDIA", lang="en", days=7, count=3)
    assert articles, "expected at least one news result"
    a = articles[0]
    assert a.title
    assert a.url.startswith("http")
    assert a.lang == "en"
