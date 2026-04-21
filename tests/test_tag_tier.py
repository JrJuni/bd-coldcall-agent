"""Tag-tier policy — full body vs snippet selection per article."""
from __future__ import annotations

import pytest

from src.llm.tag_tier import HIGH_VALUE_TAGS, has_high_value_tag, select_body_or_snippet
from src.search.base import Article


def _art(
    *,
    tags: list[str] | None = None,
    translated_body: str = "",
    body: str = "",
    snippet: str = "",
) -> Article:
    return Article(
        title="t",
        url="https://example.com/a",
        snippet=snippet,
        source="example.com",
        lang="en",
        tags=tags or [],
        translated_body=translated_body,
        body=body,
    )


# ---- HIGH_VALUE_TAGS membership -----------------------------------


def test_high_value_tag_contents():
    # Seven high-value tags per the design — pin them here so future drift is loud.
    assert HIGH_VALUE_TAGS == frozenset(
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


def test_leadership_and_other_are_low_value():
    assert "leadership" not in HIGH_VALUE_TAGS
    assert "other" not in HIGH_VALUE_TAGS


# ---- has_high_value_tag ---------------------------------------------


def test_has_high_value_tag_positive():
    assert has_high_value_tag(_art(tags=["earnings"])) is True
    assert has_high_value_tag(_art(tags=["other", "m_and_a"])) is True


def test_has_high_value_tag_negative():
    assert has_high_value_tag(_art(tags=["leadership", "other"])) is False
    assert has_high_value_tag(_art(tags=[])) is False


# ---- select_body_or_snippet -----------------------------------------


def test_high_value_returns_translated_body():
    a = _art(
        tags=["earnings"],
        translated_body="full translated body here",
        snippet="short snippet",
    )
    assert select_body_or_snippet(a) == "full translated body here"


def test_high_value_falls_back_to_body_then_snippet():
    a1 = _art(tags=["funding"], body="raw body no translation")
    assert select_body_or_snippet(a1) == "raw body no translation"
    a2 = _art(tags=["regulatory"], snippet="only snippet")
    assert select_body_or_snippet(a2) == "only snippet"


def test_low_value_returns_snippet_even_when_body_exists():
    a = _art(
        tags=["leadership"],
        translated_body="full body that we skip",
        snippet="this is the short version",
    )
    assert select_body_or_snippet(a) == "this is the short version"


def test_low_value_falls_back_to_body_when_no_snippet():
    a = _art(tags=["other"], translated_body="tb", body="raw")
    # snippet empty → next fallback is translated_body (reuse the body we have)
    assert select_body_or_snippet(a) == "tb"


def test_empty_tags_defaults_to_low_value_snippet():
    a = _art(tags=[], translated_body="tb", snippet="sn")
    assert select_body_or_snippet(a) == "sn"


def test_empty_article_returns_empty_string():
    a = _art(tags=["earnings"])
    assert select_body_or_snippet(a) == ""


def test_multi_tag_mixed_is_high_value_if_any_matches():
    a = _art(
        tags=["other", "leadership", "partnership"],
        translated_body="full body",
        snippet="snip",
    )
    # partnership is high-value → full body
    assert select_body_or_snippet(a) == "full body"
