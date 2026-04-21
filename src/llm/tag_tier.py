"""Tag-tier policy — which articles get full body vs. snippet at Sonnet time.

High-value tags (deals, earnings, partnerships, regulation) deserve full
context because they drive BD talking points directly. Low-value tags
(leadership shuffles, generic news) still count as signal but the extra
tokens don't pay their cost — snippet is enough. This tier selection is
what keeps input token usage ~35% lower than sending every body at full
length.
"""
from __future__ import annotations

from src.search.base import Article


HIGH_VALUE_TAGS: frozenset[str] = frozenset(
    {
        "earnings",
        "m_and_a",
        "partnership",
        "funding",
        "regulatory",
        "product_launch",
        "tech_launch",
    }
)


def select_body_or_snippet(article: Article) -> str:
    """Return the text payload for this article based on its tags.

    Logic:
    - At least one tag in HIGH_VALUE_TAGS → translated_body (or body, snippet fallback)
    - Otherwise → snippet
    - Always returns a non-empty string when any source is available;
      empty string only if article has no text at all.
    """
    tags = article.tags or []
    is_high_value = any(t in HIGH_VALUE_TAGS for t in tags)
    if is_high_value:
        return article.translated_body or article.body or article.snippet or ""
    return article.snippet or article.translated_body or article.body or ""


def has_high_value_tag(article: Article) -> bool:
    """Cheap predicate — used by prompt templates to mark article tier."""
    return any(t in HIGH_VALUE_TAGS for t in (article.tags or []))
