"""Article body fetcher — trafilatura-based HTML extraction.

Runs after Brave search returns URL + snippet; fills in `body` + `body_source`.
Failures fall back to snippet so the pipeline never stalls.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Optional

import httpx
import trafilatura

from .base import Article


USER_AGENT = "bd-coldcall-agent/0.1 (+research; personal BD use)"
DEFAULT_TIMEOUT = 10.0
DEFAULT_WORKERS = 5


def fetch_body(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    client: Optional[httpx.Client] = None,
) -> Optional[str]:
    """Fetch a URL and extract the main article body with trafilatura.

    Returns the extracted body (stripped) on success, or None on any failure
    (timeout, HTTP error, non-HTML, empty extraction).
    """
    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
            timeout=timeout,
            follow_redirects=True,
        )
    try:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text
        body = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if not body:
            return None
        body = body.strip()
        return body or None
    except Exception:
        return None
    finally:
        if owns_client:
            client.close()


def fetch_bodies_parallel(
    articles: list[Article],
    *,
    max_workers: int = DEFAULT_WORKERS,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[Article]:
    """Fetch bodies for many articles in parallel; preserves input order.

    For each article the returned copy has:
      body_source = "full"    → trafilatura extracted text (article.body)
      body_source = "snippet" → fetch failed, article.snippet used as body
      body_source = "empty"   → fetch failed AND snippet was also empty
    """
    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        timeout=timeout,
        follow_redirects=True,
    ) as client:

        def _task(article: Article) -> Article:
            body = fetch_body(article.url, timeout=timeout, client=client)
            if body:
                return replace(article, body=body, body_source="full")
            if article.snippet:
                return replace(article, body=article.snippet, body_source="snippet")
            return replace(article, body="", body_source="empty")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(_task, articles))


def body_stats(articles: list[Article]) -> dict:
    """Aggregate counts + average body length — written to save-file meta."""
    counts = {"full": 0, "snippet": 0, "empty": 0}
    for a in articles:
        counts[a.body_source] = counts.get(a.body_source, 0) + 1
    avg_len = int(sum(len(a.body) for a in articles) / max(len(articles), 1))
    return {
        "full": counts["full"],
        "snippet": counts["snippet"],
        "empty": counts["empty"],
        "avg_body_length": avg_len,
        "total": len(articles),
    }
