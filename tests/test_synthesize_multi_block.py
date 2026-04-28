"""Phase 8 Stream 4 — synthesize multi-channel block rendering."""
from __future__ import annotations

from datetime import datetime, timezone

from src.llm.synthesize import (
    _render_articles_by_channel,
    _render_competitor_block,
    _render_related_block,
    _render_target_block,
)
from src.search.base import Article


def _make(url: str, channel: str = "target", **kw) -> Article:
    a = Article(
        title=kw.pop("title", f"T-{url}"),
        url=url,
        snippet=kw.pop("snippet", "snip"),
        source=kw.pop("source", "src"),
        lang=kw.pop("lang", "en"),
        published_at=kw.pop("published_at", datetime(2026, 4, 20, tzinfo=timezone.utc)),
        body=kw.pop("body", ""),
        body_source=kw.pop("body_source", "empty"),
        translated_body=kw.pop("translated_body", ""),
        tags=kw.pop("tags", []),
    )
    a.channel = channel
    if kw:
        a.metadata.update(kw)
    return a


def test_render_articles_by_channel_emits_three_blocks():
    arts = [
        _make("https://t.com/1", "target", tags=["earnings"], translated_body="full target body"),
        _make("https://r.com/1", "related", intent_label="lakehouse", intent_tier="S",
              translated_body="related body that should NOT appear in full"),
        _make("https://c.com/1", "competitor", competitor_name="Snowflake",
              competitor_relation="direct", translated_body="competitor body"),
    ]
    out = _render_articles_by_channel(arts)
    assert "<target_articles>" in out
    assert "</target_articles>" in out
    assert "<related_articles>" in out
    assert "<competitor_news>" in out
    # Block order is target → related → competitor (rank order).
    assert out.index("<target_articles>") < out.index("<related_articles>") < out.index("<competitor_news>")


def test_render_articles_empty_channels_skipped():
    """Only target articles → no related/competitor blocks rendered."""
    arts = [_make("https://t.com/1", "target")]
    out = _render_articles_by_channel(arts)
    assert "<target_articles>" in out
    assert "<related_articles>" not in out
    assert "<competitor_news>" not in out


def test_target_block_uses_tag_tier_policy():
    """High-tag → translated_body in <body>; low-tag → snippet."""
    high = _make(
        "https://t.com/high", "target",
        tags=["earnings"], translated_body="HIGH FULL BODY", snippet="HIGH SNIP",
    )
    low = _make(
        "https://t.com/low", "target",
        tags=["leadership"], translated_body="LOW FULL BODY", snippet="LOW SNIP",
    )
    out = _render_target_block([high, low])
    assert "HIGH FULL BODY" in out
    assert "HIGH SNIP" not in out  # low-prio path not taken
    assert "LOW SNIP" in out
    assert "LOW FULL BODY" not in out
    # tier attributes
    assert 'tier="high"' in out
    assert 'tier="low"' in out


def test_related_block_always_uses_snippet_and_carries_intent():
    art = _make(
        "https://r.com/x", "related",
        snippet="RELATED SNIP",
        translated_body="RELATED FULL BODY MUST NOT APPEAR",
        intent_label="lakehouse_modernization",
        intent_tier="S",
    )
    out = _render_related_block([art])
    assert "RELATED SNIP" in out
    assert "RELATED FULL BODY" not in out
    assert 'intent="lakehouse_modernization"' in out
    assert 'intent_tier="S"' in out


def test_competitor_block_snippet_only_with_metadata():
    art = _make(
        "https://c.com/x", "competitor",
        snippet="COMP SNIP",
        translated_body="COMP FULL BODY MUST NOT APPEAR",
        competitor_name="Snowflake",
        competitor_relation="direct",
    )
    out = _render_competitor_block([art])
    assert "COMP SNIP" in out
    assert "COMP FULL BODY" not in out
    assert 'competitor="Snowflake"' in out
    assert 'relation="direct"' in out


def test_render_empty_articles_falls_back_to_legacy_block():
    """Zero articles → fallback `<articles>` empty block (preserves
    pre-Phase-8 prompt shape for the no-news edge case)."""
    out = _render_articles_by_channel([])
    assert "<articles>" in out
    assert "no articles provided" in out


def test_render_default_channel_is_target():
    """Article without explicit channel field defaults to target."""
    a = Article(
        title="t", url="https://x.com/a", snippet="s", source="src", lang="en",
        published_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    # Don't override channel — should default to "target".
    out = _render_articles_by_channel([a])
    assert "<target_articles>" in out
    assert "<related_articles>" not in out
