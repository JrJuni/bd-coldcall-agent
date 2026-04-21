from unittest.mock import MagicMock, patch

import pytest

from src.search.base import Article
from src.search.fetcher import body_stats, fetch_body, fetch_bodies_parallel


SAMPLE_HTML = """
<html><head><title>Test Article</title></head>
<body>
<article>
<h1>Test Article</h1>
<p>This is the main content paragraph with substantial text to look like news.
It contains multiple sentences. Here is another sentence with real information.</p>
<p>More body content here for trafilatura to find and extract cleanly.
Even more prose to ensure the extractor picks this up as the article body.</p>
</article>
<script>var ads = {};</script>
</body></html>
"""


def _article(url: str, snippet: str = "") -> Article:
    return Article(
        title=f"T-{url}",
        url=url,
        snippet=snippet,
        source="example.com",
        lang="en",
    )


def test_body_stats_counts_and_avg():
    arts = [
        Article(title="a", url="u1", snippet="", source="", lang="en", body="xxxx", body_source="full"),
        Article(title="b", url="u2", snippet="s", source="", lang="en", body="ss", body_source="snippet"),
        Article(title="c", url="u3", snippet="", source="", lang="en", body="", body_source="empty"),
    ]
    stats = body_stats(arts)
    assert stats == {"full": 1, "snippet": 1, "empty": 1, "avg_body_length": 2, "total": 3}


def test_fetch_bodies_preserves_input_order():
    arts = [_article(f"https://example.com/{i}", snippet="s") for i in range(5)]
    with patch(
        "src.search.fetcher.fetch_body",
        side_effect=lambda url, **kw: f"body-{url[-1]}",
    ):
        result = fetch_bodies_parallel(arts, max_workers=3)
    assert [a.url for a in result] == [f"https://example.com/{i}" for i in range(5)]
    assert [a.body for a in result] == [f"body-{i}" for i in range(5)]
    assert all(a.body_source == "full" for a in result)


def test_fetch_bodies_falls_back_to_snippet_on_failure():
    arts = [_article("https://example.com/x", snippet="snippet text here")]
    with patch("src.search.fetcher.fetch_body", return_value=None):
        result = fetch_bodies_parallel(arts, max_workers=1)
    assert result[0].body == "snippet text here"
    assert result[0].body_source == "snippet"


def test_fetch_bodies_empty_when_no_snippet():
    arts = [_article("https://example.com/x", snippet="")]
    with patch("src.search.fetcher.fetch_body", return_value=None):
        result = fetch_bodies_parallel(arts, max_workers=1)
    assert result[0].body == ""
    assert result[0].body_source == "empty"


def test_fetch_body_parses_html_via_trafilatura():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = SAMPLE_HTML
    fake_response.raise_for_status = MagicMock()
    fake_client.get.return_value = fake_response

    body = fetch_body("https://example.com/x", client=fake_client)
    assert body is not None
    assert "main content" in body.lower()


def test_fetch_body_returns_none_on_network_error():
    fake_client = MagicMock()
    fake_client.get.side_effect = Exception("boom")

    body = fetch_body("https://example.com/x", client=fake_client)
    assert body is None


def test_fetch_body_returns_none_on_empty_extraction():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = "<html><body></body></html>"
    fake_response.raise_for_status = MagicMock()
    fake_client.get.return_value = fake_response

    body = fetch_body("https://example.com/x", client=fake_client)
    assert body is None
